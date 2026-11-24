# Patching a live device

The image contains `/usr/local/bin/piso-patch` and a scoped sudoers rule. From your Mac:

```bash
# LAN first; once Tailscale is installed, use the tailnet IP/hostname instead.
scripts/patch-device.sh piso@<device-ip> --all      # backend + frontend + /etc/pisowifi configs
scripts/patch-device.sh piso@<device-ip> --code     # backend + rebuilt frontend only
scripts/patch-device.sh piso@<device-ip> --configs  # device configs only
```

The SSH password (from `/etc/pisowifi/ssh-credentials`) is prompted once; an SSH ControlMaster reuses the connection.

## What the patch does
1. Builds the frontend first when code is in scope — `frontend/dist` is the single source of truth.
2. Stages files in a `mktemp -d` directory on the device, verifies owner/realpath, then runs `piso-patch`.
3. `piso-patch` validates each path against an allowlist (`backend/app/`, `frontend/dist/`, `/etc/pisowifi/*`), rejects symlinks/traversal, uses `flock` against concurrent patches, backs up overwritten files to `/var/backups/pisowifi/<timestamp>/` (last 5 kept), tracks newly added files, and applies the changes.
4. Validates the result (`nginx -t`, dnsmasq test, Python import, shell/Python syntax) and restarts only affected services via an explicit map:
   - `nginx.conf` → nginx
   - `dnsmasq-main.conf` / `dnsmasq-portal.conf` → those instances
   - `firewall.sh` → firewall + sync
   - `sync.sh` → sync; `coind.py` → coind
   - backend `app/` → app + sync + coind
5. On any validation failure, SSH disconnect (SIGHUP), kill or abnormal exit: restores backups, deletes added files, restarts affected services, logs to `/var/log/piso-patch.log`, exits non-zero.

## Not patchable live
Systemd unit files, OS packages and the base image require an image rebuild + reflash. Any live patch must also be merged into the source tree, otherwise the next image rebuild silently reverts it.

## Local verification
```bash
bash tests/test_patch.sh    # stubbed systemctl/nginx/flock: 12 assertions incl. SIGHUP rollback
```
Real systemd restart semantics are not exercised off-device.
