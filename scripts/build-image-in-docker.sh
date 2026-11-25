#!/usr/bin/env bash
# Runs INSIDE privileged debian:trixie with /work (repo) and /build mounted.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

URL="https://dl.armbian.com/orangepione/archive/Armbian_26.8.1_Orangepione_trixie_current_6.18.44_minimal.img.xz"
ROOTFS=/mnt/piso-rootfs

echo "[builder] Installing host tools..."
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  qemu-user-static binfmt-support parted e2fsprogs xz-utils curl \
  ca-certificates rsync file dosfstools

update-binfmts --enable qemu-arm 2>/dev/null || true
mkdir -p /proc/sys/fs/binfmt_misc 2>/dev/null || true
mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true

echo "[builder] Downloading Armbian image..."
cd /build
if [ ! -f armbian.img.xz ]; then
  curl -fsSL -o armbian.img.xz "$URL"
  curl -fsSL -o armbian.img.xz.sha "$URL.sha"
fi
expected="$(awk '{print $1}' armbian.img.xz.sha)"
actual="$(sha256sum armbian.img.xz | awk '{print $1}')"
if [ "$expected" != "$actual" ]; then
  echo "checksum mismatch: expected $expected got $actual" >&2
  exit 1
fi
xz -dkf armbian.img.xz
cp -f armbian.img pisowifi-opi-one.img
truncate -s +1800M pisowifi-opi-one.img

echo "[builder] Expanding partition..."
LOOP="$(losetup -f --show pisowifi-opi-one.img)"
parted -s "$LOOP" resizepart 1 100%
start="$(parted -s "$LOOP" unit s print | awk '/^ 1 /{gsub("s","",$2); print $2; exit}')"
offset=$((start * 512))
PARTLOOP="$(losetup -f --show --offset "$offset" pisowifi-opi-one.img)"
e2fsck -fy "$PARTLOOP" >/dev/null
resize2fs "$PARTLOOP" >/dev/null
mkdir -p "$ROOTFS"
mount "$PARTLOOP" "$ROOTFS"

cleanup() {
  umount "$ROOTFS" 2>/dev/null || true
  losetup -d "$PARTLOOP" 2>/dev/null || true
  losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup EXIT

echo "[builder] Copying app, frontend, configs and wheels..."
mkdir -p "$ROOTFS/opt/pisowifi/backend" "$ROOTFS/opt/pisowifi/frontend/dist" \
         "$ROOTFS/opt/pisowifi/wheels" "$ROOTFS/etc/pisowifi" \
         "$ROOTFS/lib/systemd/system" "$ROOTFS/usr/lib/systemd/network" \
         "$ROOTFS/var/lib/pisowifi"
cp -a /work/backend/app "$ROOTFS/opt/pisowifi/backend/"
cp /work/device/version "$ROOTFS/opt/pisowifi/backend/app/version"
cp -a /work/frontend/dist/. "$ROOTFS/opt/pisowifi/frontend/dist/"
cp -a /build/wheels/. "$ROOTFS/opt/pisowifi/wheels/"
cp /work/device/dnsmasq-main.conf /work/device/dnsmasq-portal.conf \
   /work/device/nginx.conf /work/device/firewall.sh /work/device/sync.sh \
   /work/device/qos.sh /work/device/coind.py "$ROOTFS/etc/pisowifi/"
cp /work/device/10-piso-guest.link "$ROOTFS/usr/lib/systemd/network/"
mkdir -p "$ROOTFS/usr/local/bin" "$ROOTFS/var/backups/pisowifi"
cp /work/device/piso-patch "$ROOTFS/usr/local/bin/"
chmod 755 "$ROOTFS/usr/local/bin/piso-patch"
touch "$ROOTFS/var/log/piso-patch.log"
for unit in pisowifi-network pisowifi-firewall pisowifi-app pisowifi-sync \
            pisowifi-coind pisowifi-qos dnsmasq-main dnsmasq-portal; do
  cp "/work/device/$unit.service" "$ROOTFS/lib/systemd/system/"
done
chmod +x "$ROOTFS/etc/pisowifi/qos.sh" "$ROOTFS/etc/pisowifi/firewall.sh" "$ROOTFS/etc/pisowifi/sync.sh" 2>/dev/null || true
cp /usr/bin/qemu-arm-static "$ROOTFS/usr/bin/" 2>/dev/null || true
rm -f "$ROOTFS/etc/resolv.conf"
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"

echo "[builder] Installing device packages and configuring rootfs..."
# SD-wear hardening: tmpfs for volatile logs + WAL-friendly DB (actual mounts happen at boot)
cat >> "$ROOTFS/etc/fstab" <<'FSTAB'

# Piso: RAM logs — avoids constant SD writes; pisowifi-sync checkpoints WAL every 30s
tmpfs /var/log tmpfs defaults,noatime,nosuid,mode=0755,size=50M 0 0
tmpfs /var/tmp tmpfs defaults,noatime,nosuid,mode=0755,size=20M 0 0
FSTAB
mkdir -p "$ROOTFS/etc/systemd/journald.conf.d"
cat > "$ROOTFS/etc/systemd/journald.conf.d/99-piso-volatile.conf" <<'JC'
[Journal]
Storage=volatile
RuntimeMaxUse=30M
SystemMaxUse=30M
JC
# Ensure /var/log exists after tmpfs mount
mkdir -p "$ROOTFS/var/log/journal"

chroot "$ROOTFS" /bin/bash <<'CHROOT'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv nginx ipset iptables dnsmasq openssh-server iproute2 \
  gpiod sudo openssl curl wget ca-certificates gnupg

python3 -m venv /opt/pisowifi/venv
/opt/pisowifi/venv/bin/pip install --quiet --no-index \
  --find-links=/opt/pisowifi/wheels fastapi uvicorn pydantic PyJWT

# Runtime env: random JWT secret; fixed admin password admin@123; no mock MAC on the device.
secret="$(openssl rand -hex 32)"
previewpass="$(openssl rand -base64 18)"
printf 'preview:%s\n' "$(openssl passwd -apr1 "$previewpass")" > /etc/pisowifi/htpasswd
printf 'user: admin\npassword: %s\n' "$previewpass" > /etc/pisowifi/preview-credentials
chmod 600 /etc/pisowifi/htpasswd /etc/pisowifi/preview-credentials
# Default admin password is fixed to admin@123 — warn in console to change it.
printf 'user: admin\npassword: admin@123\n' > /etc/pisowifi/admin-credentials
chmod 600 /etc/pisowifi/admin-credentials
cat > /etc/pisowifi/app.env <<EOF
PISO_DB_PATH=/var/lib/pisowifi/pisowifi.db
PISO_JWT_SECRET=$secret
PISO_ADMIN_USER=admin
PISO_ADMIN_PASS=admin@123
EOF
chmod 600 /etc/pisowifi/app.env

# SSH user for terminal access; Tailscale installed manually by the user.
useradd -m -s /bin/bash piso 2>/dev/null || true
echo 'piso ALL=(root) NOPASSWD: /usr/local/bin/piso-patch, /usr/bin/apt-get, /usr/bin/apt, /usr/bin/gpg, /usr/bin/tee, /usr/bin/systemctl, /usr/bin/journalctl, /usr/sbin/usermod, /usr/bin/ethtool, /usr/bin/tailscale, /usr/sbin/tailscale' > /etc/sudoers.d/piso
chmod 440 /etc/sudoers.d/piso
sshpass="$(openssl rand -base64 18)"
echo "piso:$sshpass" | chpasswd
printf 'user: piso\npassword: %s\n' "$sshpass" > /etc/pisowifi/ssh-credentials
chmod 600 /etc/pisowifi/ssh-credentials

sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/pisowifi/nginx.conf /etc/nginx/sites-enabled/pisowifi
nginx -t

for unit in pisowifi-network pisowifi-firewall pisowifi-app pisowifi-sync \
            pisowifi-coind pisowifi-qos dnsmasq-main dnsmasq-portal ssh; do
  SYSTEMD_OFFLINE=1 systemctl enable "$unit" 2>/dev/null || true
done
# Stock dnsmasq would grab port 53 before dnsmasq-main; disable and mask it.
SYSTEMD_OFFLINE=1 systemctl disable dnsmasq.service 2>/dev/null || true
ln -sf /dev/null /etc/systemd/system/dnsmasq.service

# Explicit seed now (idempotent at startup too).
cd /opt/pisowifi/backend
PISO_DB_PATH=/var/lib/pisowifi/pisowifi.db \
PISO_ADMIN_USER=admin PISO_ADMIN_PASS=admin@123 PISO_JWT_SECRET="$secret" \
/opt/pisowifi/venv/bin/python -c 'from app import db; db.init_db()'
CHROOT

echo "[builder] Exporting fresh credentials to host secrets/..."
mkdir -p /work/secrets /build/secrets
cp -a "$ROOTFS/etc/pisowifi/ssh-credentials" /work/secrets/ssh-credentials
cp -a "$ROOTFS/etc/pisowifi/ssh-credentials" /build/secrets/ssh-credentials
cp -a "$ROOTFS/etc/pisowifi/admin-credentials" /work/secrets/admin-credentials
cp -a "$ROOTFS/etc/pisowifi/admin-credentials" /build/secrets/admin-credentials
chmod 600 /work/secrets/ssh-credentials /work/secrets/admin-credentials 2>/dev/null || true
chmod 600 /build/secrets/ssh-credentials /build/secrets/admin-credentials 2>/dev/null || true
cp -a "$ROOTFS/etc/pisowifi/ssh-credentials" /build/ssh-credentials 2>/dev/null || true
cp -a "$ROOTFS/etc/pisowifi/admin-credentials" /build/admin-credentials 2>/dev/null || true
# Also keep a copy of preview credentials separately for reference
cp -a "$ROOTFS/etc/pisowifi/preview-credentials" /work/secrets/preview-credentials 2>/dev/null || true
cp -a "$ROOTFS/etc/pisowifi/preview-credentials" /build/preview-credentials 2>/dev/null || true
echo "[builder] secrets exported to /work/secrets/ (and /build/secrets/) — mode 0600"

echo "[builder] Verifying rootfs..."
chroot "$ROOTFS" /opt/pisowifi/venv/bin/python -c "import fastapi, uvicorn, jwt; print('python deps OK')"
chroot "$ROOTFS" nginx -t
chroot "$ROOTFS" test -x /usr/local/bin/piso-patch
for unit in pisowifi-app pisowifi-firewall dnsmasq-main dnsmasq-portal pisowifi-coind; do
  chroot "$ROOTFS" systemd-analyze verify "/lib/systemd/system/$unit.service" 2>/dev/null || true
done

cleanup
trap - EXIT
sha256sum pisowifi-opi-one.img > pisowifi-opi-one.img.sha256
echo "[builder] image ready: /build/pisowifi-opi-one.img"
