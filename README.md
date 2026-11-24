# Piso WiFi clone

Clean-room functional clone of the core of AdoPiSoft: captive portal, coin/voucher time purchase, session tracking, admin console, per-client DNS interception, and a flashable Orange Pi One SD-card image.

- `backend/` — FastAPI + SQLite API.
- `frontend/` — Vue 3 portal at `/`, admin console at `/console`, portal preview at `/console/preview`.
- `device/` — dnsmasq, nginx, firewall, sync, coind configs and systemd units.
- `scripts/build-image.sh` — builds `build/pisowifi-opi-one.img`.
- `scripts/patch-device.sh` + `device/piso-patch` — SSH patching with backup/rollback.
- `docs/FLASH.md` — flashing, first boot, wiring, manual Tailscale install.
- `docs/PATCH.md` — live patching rules and limits.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && PISO_MOCK_MAC=aa:bb:cc:dd:ee:01 ../.venv/bin/uvicorn app.main:app --port 8000
# separate shell:
cd frontend && npm install && npm run dev
```

Portal: http://localhost:5173/ · Admin console: http://localhost:5173/console (`admin`; password generated on first start in `data/admin-credentials`). On the device, the customer VLAN serves the portal at `http://10.0.0.1/` and the console is on the LAN IP at `/console`.

Or `docker compose up --build`.

In dev mode the portal has a device switcher that sets `X-Dev-Mac`, so you can verify per-device coin balances.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest tests -q
```

## Defaults
- Plans: 30 min / 1 coin, 1 hour / 2 coins, 2 hours / 4 coins.
- GPIO pins (device): coin pulse physical #3 (PA12), relay #11 (PA1), option #5 (PA11).
- Admin: `admin`; generated password at `data/admin-credentials` locally, `/var/lib/pisowifi/admin-credentials` on the device. Portal preview uses `admin` and `/etc/pisowifi/preview-credentials`.
- SSH user on the final image: `piso`, password in `/etc/pisowifi/ssh-credentials`. Tailscale is installed manually.

## Build the SD image
```bash
bash scripts/build-image.sh     # produces build/pisowifi-opi-one.img + .sha256
```
Requires Docker with privileged mode (loop devices) and network access. See `docs/FLASH.md` for flashing and first boot.

## Not implemented
Real payment gateway, email/social/WhatsApp OTP login, multi-tenancy, hostapd/on-board WiFi (external AP in bridge mode is required), baked Tailscale, DoH/DoT interception, and real-hardware verification.
