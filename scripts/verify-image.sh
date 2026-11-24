#!/usr/bin/env bash
# Static verification of the built SD image (no hardware required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"

docker run --rm --privileged --userns=host \
  --dns 1.1.1.1 --dns 8.8.8.8 \
  -v "$BUILD:/build" \
  debian:trixie bash -c '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends e2fsprogs file parted >/dev/null
cd /build
LOOP=$(losetup -f --show pisowifi-opi-one.img)
start=$(parted -s "$LOOP" unit s print 2>/dev/null | awk "/^ 1 /{gsub(\"s\",\"\",\$2); print \$2; exit}" || echo 8192)
offset=$((start * 512))
PART=$(losetup -f --show --offset "$offset" pisowifi-opi-one.img)
mkdir -p /mnt/verify
mount -o ro "$PART" /mnt/verify
R=/mnt/verify
fail=0
check() { if eval "$2"; then echo "OK   $1"; else echo "FAIL $1"; fail=1; fi; }

check "boot files"            "test -d $R/boot && ls $R/boot | grep -q ."
check "app backend"           "test -f $R/opt/pisowifi/backend/app/main.py"
check "frontend dist"         "test -f $R/opt/pisowifi/frontend/dist/index.html"
check "venv fastapi"          "test -d $R/opt/pisowifi/venv/lib/python3.13/site-packages/fastapi"
check "dns configs"           "test -f $R/etc/pisowifi/dnsmasq-main.conf && test -f $R/etc/pisowifi/dnsmasq-portal.conf"
check "guest NIC rename"      "test -f $R/usr/lib/systemd/network/10-piso-guest.link && grep -q 'Name=guest0' $R/usr/lib/systemd/network/10-piso-guest.link"
check "dns main bind :53"     "grep -q \"listen-address=10.0.0.1\" $R/etc/pisowifi/dnsmasq-main.conf && grep -q \"port=53\" $R/etc/pisowifi/dnsmasq-main.conf"
check "dns portal bind :5353" "grep -q \"port=5353\" $R/etc/pisowifi/dnsmasq-portal.conf"
check "dns wildcard + ttl"    "grep -q \"address=/#/10.0.0.1\" $R/etc/pisowifi/dnsmasq-portal.conf && grep -q \"local-ttl=5\" $R/etc/pisowifi/dnsmasq-portal.conf"
check "firewall conntrack"    "grep -q -- \"--ctstate ESTABLISHED,RELATED\" $R/etc/pisowifi/firewall.sh"
check "firewall dns redirect" "grep -q -- \"--to-ports 5353\" $R/etc/pisowifi/firewall.sh"
check "firewall http redirect" "grep -q -- \"--dport 80\" $R/etc/pisowifi/firewall.sh"
check "nginx preview proxy"   "grep -q \"/preview-portal/\" $R/etc/pisowifi/nginx.conf"
check "preview auth"          "grep -q auth_basic_user_file $R/etc/pisowifi/nginx.conf && test -f $R/etc/pisowifi/htpasswd"
check "preview credentials"   "test -f $R/etc/pisowifi/preview-credentials"
check "no frame headers"      "! grep -qi \"X-Frame-Options\" $R/etc/pisowifi/nginx.conf"
check "admin credentials"     "test -f $R/var/lib/pisowifi/admin-credentials"
check "coind present"         "test -f $R/etc/pisowifi/coind.py"
check "admin seeded"          "test -f $R/var/lib/pisowifi/pisowifi.db"
check "ssh credentials"       "test -f $R/etc/pisowifi/ssh-credentials"
check "app env"               "grep -q PISO_JWT_SECRET $R/etc/pisowifi/app.env"
check "tailscale absent"      "! test -d $R/etc/apt/sources.list.d/tailscale.list"
check "unit symlinks"         "ls $R/etc/systemd/system/multi-user.target.wants/ | grep -q pisowifi-app.service"
check "generic dnsmasq off"   "! test -e $R/etc/systemd/system/multi-user.target.wants/dnsmasq.service"
check "generic dnsmasq masked" "readlink $R/etc/systemd/system/dnsmasq.service | grep -q /dev/null"
check "piso-patch installed"  "test -x $R/usr/local/bin/piso-patch"
check "patch backup dir"      "test -d $R/var/backups/pisowifi"
check "patch log"             "test -f $R/var/log/piso-patch.log"
check "sudoers scoped"        "grep -q \"/usr/local/bin/piso-patch\" $R/etc/sudoers.d/piso && ! grep -q \"ALL=(ALL)\" $R/etc/sudoers.d/piso"

umount /mnt/verify
losetup -d "$PART" 2>/dev/null || true
losetup -d "$LOOP" 2>/dev/null || true
exit $fail
'
