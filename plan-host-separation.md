# Plan: Host-based UI separation

## Goal
- captive.apple.com -> guest
- 10.0.0.1 -> guest
- 192.168.100.27 -> admin only, "/" shows only system status, hide Console link
- 192.168.100.27/console -> admin only (login + console)

## Enforce at two layers (Jev: both 0.79)
1. **nginx (authoritative, device only)** – separate server blocks by listen IP + server_name so wrong Host/Path combos never serve the SPA shell.
2. **frontend (UX)** – host-aware router guard + host-aware root view so dev/localhost and fallback paths still behave correctly.

## Changes (minimal, ponytail)

### device/nginx.conf (only on device; docker-compose uses frontend/nginx.conf unchanged)
- Keep map $piso_real_ip.
- **Guest block:** `listen 10.0.0.1:80; server_name 10.0.0.1 captive.apple.com;` – serves `/opt/pisowifi/frontend/dist` + /api proxy + SPA fallback. Keep assets working via `try_files $uri $uri/ /index.html`. Add `location ~ ^/console { return 404; }` BEFORE the catch-all so guest never gets console shell (assets still served via preceding `location /assets/` if needed, but simplest: console block returns 404 before SPA fallback; static assets under /assets/ are not under /console so not blocked).
- **Admin block:** `listen 192.168.100.27:80; server_name 192.168.100.27;` – same root + /api proxy + SPA fallback via `try_files $uri $uri/ /index.html`. Do NOT whitelist only `/` and `/console`; allow all SPA routes so `/assets/*`, `*.js`, `favicon` work. Frontend guard is the enforcer (admin host "/" renders AdminRootView at same URL, not a new /admin-status path). This avoids 404ing static assets.
- **Default block:** `listen 80 default_server; server_name _;` – keep for localhost/dev and unknown hosts: serve SPA + /api proxy. Note: `default_server` does NOT prevent startup failure if 10.0.0.1/192.168.100.27 missing; but device/nginx.conf is never parsed by docker-compose (compose uses frontend/nginx.conf), and on device both IPs exist so listens succeed. No change to frontend/nginx.conf.

### frontend/src/utils/host.js (new, ~20 lines)
- Use `location.hostname` (port-stripped) not `location.host`.
- `isGuestHost()` -> hostname in ['captive.apple.com','10.0.0.1'] 
- `isAdminHost()` -> hostname === '192.168.100.27'
- `isNeutralHost()` -> true when `!isGuestHost && !isAdminHost` (covers localhost, 127.0.0.1, ::1, and LAN dev IPs like 192.168.1.x). Explicitly allow both guest and admin routes on neutral hosts for dev/test. Guard logic: if neutral -> allow any path.
- Used by router + views.

### frontend/src/views/AdminRootView.vue (new, ~40 lines)
- Minimal admin landing **at** `192.168.100.27/` (same URL, no redirect) – shows only system status: one StatCard "System status / Active clients" from `/api/admin/overview` when authed. If not authed, show "Admin – sign in at /console" text (no stats, no auto-redirect, no Console button per spec "hide button to console link"). No revenue/vouchers/coins cards.
- Mobile-first, no horizontal scroll.

### frontend/src/main.js + frontend/src/views/HostRoot.vue (or inline wrapper)
- Add `HostRoot.vue` wrapper at `/`: renders `AdminRootView` when `isAdminHost()`, otherwise `PortalView`. No URL change – `192.168.100.27/` stays `/` but shows admin status. Alternative is route `beforeEnter` returning different component – wrapper is simpler and avoids `/admin-status` whitelist problem flagged by challenger.
- Global `beforeEach` guard:
  - if isGuestHost() && to.path startsWith '/console' -> next('/')
  - if isAdminHost() && to.path startsWith '/console/preview' -> allow (admin can preview)
  - if isGuestHost() && to.path === '/console/preview' -> next('/')
  - neutral hosts: allow everything
- Keep `/:pathMatch(.*)*` redirect but guard runs first.

### frontend/src/views/PortalView.vue
- Hide `router-link to="/console"` when isAdminHost() (or when not guest/neutral). Guard already prevents reaching console, but hide button fulfills "hide button to console link" on admin side. Use `v-if="!isAdminHost"` on that link.

### frontend/src/views/AdminView.vue
- No change needed except guard ensures it only renders on admin/neutral hosts. Optionally hide "Portal" link when isAdminHost? Spec says admin root hides console link; console itself keeps Portal link? Keep as is – but if admin root is separate, console's Portal link could point to "/" which is admin status (ok). Leave.

## Verification
- `npm run build` (frontend) + check dist contains host.js logic
- Browser/MCP at 390×844 and 1200×900 (not curl Host header – Vue guard uses `location.hostname`): open `http://10.0.0.1/` -> PortalView guest, `http://10.0.0.1/console` -> redirects to `/`; open `http://192.168.100.27/` -> AdminRootView only one StatCard, no Console button; `http://192.168.100.27/console` -> AdminView login; localhost/127.0.0.1 -> both routes allowed for dev.
- Backend pytest still passes (no backend change).
- `bash tests/test_patch.sh` passes (nginx still serves dist).

## Out of scope (skip)
- Real DNS interception for captive.apple.com (already handled by dnsmasq-portal.conf)
- Backend Host header validation (frontend+nginx sufficient; backend still auth-gated)
- Changing firewall / device IPs – assume 192.168.100.27 is static.

## Risks
- localhost dev must remain neutral – guard must not block devs.
- nginx listen IP binding on dev machine will fail if IP not present – keep default_server permissive so docker-compose build not affected.
