# Flash & first boot — Orange Pi One

Produced by `scripts/build-image.sh`: `build/pisowifi-opi-one.img` (+ `.sha256`).

## What the image contains
- Armbian Trixie armhf (kernel 6.18.x), clean base — the proprietary AdoPiSoft image is not used.
- App in `/opt/pisowifi/backend`, frontend in `/opt/pisowifi/frontend/dist`, venv `/opt/pisowifi/venv`.
- Guest VLAN `10.0.0.0/24`: portal/gateway `10.0.0.1`, DHCP `.50–.200`.
- DNS interception: unauthorized guests → `dnsmasq-portal` (:5353, wildcard, 5 s TTL); authorized guests → `dnsmasq-main` (:53, upstream).
- iptables/ipset gating, applied at every boot by `pisowifi-firewall.service`.
- `sshd` with user `piso`, password in `/etc/pisowifi/ssh-credentials` (0600), passwordless sudo.
- Tailscale is **not** installed — install it manually (below).

## Flash
Verify the checksum, then write to a microSD (≥8 GB):

```bash
shasum -a 256 -c build/pisowifi-opi-one.img.sha256
# macOS: identify the disk with `diskutil list`, unmount, then:
sudo dd if=build/pisowifi-opi-one.img of=/dev/rdiskN bs=1m status=progress
```

Or use BalenaEtcher with the `.img` file.

## Wiring
- **WAN**: built-in RJ45 (`end0` on Orange Pi One) → your internet router.
- **Guest LAN**: USB port → USB→Ethernet dongle (renamed to `guest0`) → external WiFi AP. The AP **must be in bridge/AP mode**, not NAT/router mode, so guest MACs are visible and the board — not the AP — hands out 10.0.0.x leases.
- **Coinslot**: NO contact, pull-up/divider to ≤3.3 V on physical pin #3 (PA12); common ground with pin #6; relay on pin #11 (PA1) or #5 (PA11). **Never feed 12 V into a GPIO pin.**

## First boot
1. Wait 1–2 minutes for services to settle.
2. **Admin console** (from a device on the same LAN as `end0`): `http://<board-lan-ip>/console` — login `admin` with the generated password in `/var/lib/pisowifi/admin-credentials`.
3. **Guest portal** (from the guest VLAN): `http://10.0.0.1/`.
4. **Portal preview** from the admin console: `http://<board-lan-ip>/console/preview` — served through nginx's same-origin `/preview-portal/` proxy, so your admin PC needs no route to `10.0.0.1`. Basic auth uses `admin` and the password in `/etc/pisowifi/preview-credentials`.
5. **SSH**: `ssh piso@<board-lan-ip>` with the password from `/etc/pisowifi/ssh-credentials`.

## Patching after go-live
See `docs/PATCH.md` — app, frontend and `/etc/pisowifi` configs can be patched over SSH with backup/rollback. Systemd units and OS packages require an image rebuild.

## Install Tailscale manually (optional)
```bash
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/tailscale-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian trixie main" \
  | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update && sudo apt-get install -y tailscale
sudo tailscale up --ssh
```

## Useful checks on the device
```bash
systemctl status pisowifi-app pisowifi-firewall pisowifi-sync \
  dnsmasq-main dnsmasq-portal pisowifi-coind nginx ssh
ipset list pisowifi_allow
iptables -t nat -L PISO_PRE -n -v
curl -s http://127.0.0.1:8000/api/internal/allowed-macs
```

## Known limitations
- DNS interception cannot force clients using encrypted DNS (DoH/DoT) to the portal.
- H3 GPIO pin offsets come from a static table; confirm with `gpioinfo` on your board.
- A tagged customer VLAN needs a VLAN subinterface instead of plain `guest0`.
- Real-board boot, GPIO pulses and Tailscale join cannot be verified off-hardware.
