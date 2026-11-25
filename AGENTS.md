# AGENTS.md — Piso WiFi clone

Clean-room clone of the core of AdoPiSoft: captive portal, coin/voucher time purchase,
session tracking, admin console, per-client DNS interception, and an Orange Pi One SD-card
image. This file holds project-specific rules for agents; keep it short and current.

## Layout

- `backend/` — FastAPI + SQLite API. All HTTP routes live in `backend/app/main.py`;
  `config.py` (env/settings + GPIO pin map), `auth.py` (password/JWT), `db.py` (schema/tx helpers).
  Tests: `backend/tests/test_api.py`.
- `frontend/` — Vue 3 portal (`/`), admin console (`/console`), portal preview (`/console/preview`).
  `src/views/` for pages, `src/components/` for shared UI, `src/api.js` for all HTTP calls.
- `device/` — dnsmasq, nginx, firewall, sync, coind configs and systemd units.
- `scripts/` — `build-image.sh`, `patch-device.sh`, `verify-image.sh`, `build-image-in-docker.sh`.
- `docs/FLASH.md` (flashing/first boot), `docs/PATCH.md` (live patch rules).
- `tests/test_patch.sh` — local stubbed verification of the patch/rollback flow.
- `data/` — local SQLite DB + generated credentials; gitignored, never commit.
- `secrets/` — local copies of the image's SSH/admin credentials; gitignored, never commit.

## Stack (respect the pinned versions)

- Backend: Python 3.13, FastAPI 0.165, pydantic 2, PyJWT, stdlib `sqlite3` (no ORM), pytest.
- Frontend: Vue 3.5 + vue-router 4, Vite 7, Tailwind CSS 4 via `@tailwindcss/vite`, Node 22.
- Deploy: `docker-compose.yml` (backend not published; frontend on `:5173`). Device services are
  systemd units; frontend `dist/` is the single source of truth for what runs on the device.

## Commands

```bash
# backend (from backend/)
../.venv/bin/python -m pytest tests -q          # fast, uses temp DB + mock MAC

# frontend
cd frontend && npm install && npm run dev       # dev server :5173, /api proxied to :8000
npm run build                                    # emits frontend/dist (needed before a device patch)

# full stack
docker compose up --build

# device
bash tests/test_patch.sh                         # stubbed patch validation, no hardware
bash scripts/build-image.sh                      # build/pisowifi-opi-one.img (+ .sha256)

# deploy to a live device (scope chosen from the diff via Laya/Jev)
/deploy piso@192.168.1.50                        # see .opencode/commands/deploy.md

# image version: device/version (MAJOR.MINOR.PATCH) is the source; /rebuild and /deploy bump it via
# Laya/Jev before building/staging, and it installs as backend/app/version (patchable on all devices)
```

## Backend conventions

- One module (`main.py`) holds all endpoints; keep related routes in their existing sections
  (`Public portal`, `Auth + admin`, `Internal (loopback only on device)`).
- Every write uses `with db.write_tx(conn):` (BEGIN IMMEDIATE); reads use plain `db.connect()`.
  Always close connections. Use `db.now_iso()` / `db.expiry_iso()` for UTC ISO timestamps.
- Admin routes depend on `Depends(require_admin)`; public portal routes do not. Never weaken this.
- Client identity is derived **server-side** from the neighbor table (`client_mac`/`neighbor_mac`),
  and fails closed. `PISO_MOCK_MAC` and the `X-Dev-Mac` header are **dev/test only** — never set
  or enable them in the device image.
- Config comes from `PISO_*` env vars. Default admin is `admin` / `admin@123`
  (`PISO_ADMIN_USER` / `PISO_ADMIN_PASS` to override); console shows a warning while the
  default is active — change it on first login. JWT secret via `PISO_JWT_SECRET` must stay
  out of source; any generated secrets are persisted next to the DB with mode `0600`.
- Sessions are the source of truth for access (`db.allowed_macs`); purchases/redeems insert a
  session, coin/voucher changes also write a transaction. Keep these together in one transaction.

## Frontend conventions

- Use the existing shared components in `src/components/` (`ConfirmDialog`, `DataTable`,
  `StatCard`) before writing new markup; do not duplicate their behaviour in views.
- All API calls go through `src/api.js` (`get`/`post`/`put`/`del`). It attaches the bearer token
  and, in dev only, the `X-Dev-Mac` override. Do not call `fetch` directly from views.
- Token and dev MAC live in `localStorage` (`piso-token`, `piso-dev-mac`); dev MAC is ignored in
  production builds by `import.meta.env.DEV` guards. Keep it that way.
- Tailwind 4 is imported once in `src/style.css`; use utility classes, no new CSS framework.
- Confirmation for destructive/mutating actions (delete voucher, revoke session, change plan,
  etc.) via `ConfirmDialog`. Mobile-first: no horizontal scroll at 360–390px, touch targets ≥44px.

## Device & patch conventions

- GPIO is accessed only when `PISO_GPIO_ENABLED=1`, through `PIN_MAP` in `config.py`
  (physical pins 3/5/11). Host/mock mode must stay a no-op for relay/gpio calls.
- `/api/internal/*` endpoints are loopback-only on the device; never expose them to guests.
- Live patching (`piso-patch`) allows only `backend/app/`, `frontend/dist/`, and `/etc/pisowifi/*`:
  no symlinks/traversal, `flock` serialisation, backups with rollback on any failure.
- **Any live patch must also be merged into this source tree**, or the next image rebuild
  silently reverts it. Systemd units, OS packages and the base image need a rebuild + reflash.
- Every image rebuild regenerates the SSH and admin passwords: refresh both `secrets/ssh-credentials`
  and `secrets/admin-credentials` from the new image (mode `0600`) before using them.

### SSH patching

- Invoke from the project root: `scripts/patch-device.sh piso@<device-ip> --all|--code|--configs`.
  `--code` = backend app + rebuilt `frontend/dist`; `--configs` = device configs only;
  `--all` = both. The flag is `--configs` (plural) — `--config` is rejected by the script.
- SSH user is `piso`; its password is in `/etc/pisowifi/ssh-credentials` on the device (never commit
  it). Reach the device on the LAN first; once Tailscale is installed, use its tailnet IP/hostname.
- The script prompts for the SSH password once and opens a ControlMaster (`-M -S`,
  `ControlPersist=5m`) reused by rsync and the remote commands; the socket is closed on exit.
- `/deploy` wraps this flow: inspects the diff, uses Laya (Jev fallback) to pick the scope, asks for
  confirmation, then checks the log for `OK: patch applied` versus `ROLLBACK`.
- **`OK: patch applied` is not enough — verify the captive portal on the device before reporting
  a live patch done.** Primary (SSH): confirm `pisowifi-app` actually restarted (`systemctl show pisowifi-app
  -p ActiveEnterTimestamp --value` newer than the patch), all of `dnsmasq-main`, `dnsmasq-portal`,
  `pisowifi-firewall`, `pisowifi-app`, `nginx` are `active`, `curl --interface 10.0.0.1
  http://10.0.0.1/` returns `200` with the portal from `frontend/dist`, and a DNS query for any
  name to `10.0.0.1:5353` answers `10.0.0.1`. Fallback (no SSH): verify from LAN that `curl http://192.168.100.27/api/portal/config` is `200` with current `frontend/dist`, and `curl -H "Host: captive.apple.com" http://192.168.100.27/hotspot-detect.html` returns `200` portal HTML (not `Success`), plus `nmap -p 22,80 192.168.100.27` shows `open`. `guest0` must be `state UP` with a client attached:
  `NO-CARRIER` is an AP/link problem, not a patch failure (external AP in bridge mode is required).
  An admin endpoint (`/api/admin/*`) returning `200` does not prove guests reach the portal.

## Security invariants (do not relax)

- Never trust a client-supplied MAC; never log secrets or credential contents.
- Guest portal must not reach admin/internal endpoints; keep auth dependencies and firewall rules.
- Keep `.env*`, `data/`, `*.img*`, and credential files out of git (see `.gitignore`).

## Verification before "done"

- Backend change → run the pytest suite (add a test for new behaviour, including auth/402/409 paths).
- Frontend change → `npm run build`, then verify in the browser at 390×844 and 1200×900
  (no horizontal scroll, tables collapse to cards on mobile).
- Device/config/patch change → `bash tests/test_patch.sh`; note that real hardware/systemd
  behaviour is not exercised off-device and needs an on-device check. For a live patch, run the
  captive-portal checks in Device & patch conventions above before reporting success.

## Not implemented (out of scope unless asked)

Real payment gateway, email/social/WhatsApp OTP, multi-tenancy, hostapd/on-board WiFi (external AP
in bridge mode required), baked Tailscale, DoH/DoT interception, real-hardware verification.
