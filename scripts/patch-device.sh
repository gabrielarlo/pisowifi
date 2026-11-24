#!/usr/bin/env bash
# Patch a live device over SSH. Usage:
#   scripts/patch-device.sh <user@host> [--code|--configs|--all]
# Example: scripts/patch-device.sh piso@192.168.1.50 --all
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-}"
SCOPE="${2:---all}"
if [ -z "$TARGET" ]; then
  echo "usage: $0 <user@host> [--code|--configs|--all]" >&2
  exit 1
fi

case "$SCOPE" in
  --code|--configs|--all) ;;
  *) echo "unknown scope: $SCOPE" >&2; exit 1 ;;
esac

if [ "$SCOPE" = "--code" ] || [ "$SCOPE" = "--all" ]; then
  echo "Building frontend (dist is the source of truth)..."
  (cd "$ROOT/frontend" && npm run build >/dev/null)
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"; [ -n "${CTL:-}" ] && ssh -S "$CTL" -O exit "$TARGET" 2>/dev/null || true' EXIT

mkdir -p "$STAGE/backend/app" "$STAGE/frontend/dist" "$STAGE/device"
if [ "$SCOPE" = "--code" ] || [ "$SCOPE" = "--all" ]; then
  cp -a "$ROOT/backend/app/." "$STAGE/backend/app/"
  cp -a "$ROOT/frontend/dist/." "$STAGE/frontend/dist/"
fi
if [ "$SCOPE" = "--configs" ] || [ "$SCOPE" = "--all" ]; then
  for f in nginx.conf dnsmasq-main.conf dnsmasq-portal.conf firewall.sh sync.sh coind.py; do
    cp "$ROOT/device/$f" "$STAGE/device/"
  done
fi

# One SSH password prompt, reused by rsync and the device command.
CTL="$(mktemp -u /tmp/piso-ssh.XXXXXX)"
ssh -M -S "$CTL" -o ControlPersist=5m -fN "$TARGET"

REMOTE_STAGE="$(ssh -S "$CTL" "$TARGET" 'mktemp -d /tmp/piso-patch.XXXXXX')"
owner="$(ssh -S "$CTL" "$TARGET" "stat -c %U '$REMOTE_STAGE'")"
real="$(ssh -S "$CTL" "$TARGET" "realpath '$REMOTE_STAGE'")"
[ "$owner" = "$(echo "$TARGET" | cut -d@ -f1)" ] || { echo "staging owner mismatch" >&2; exit 1; }
case "$real" in /tmp/piso-patch.*) ;; *) echo "staging realpath mismatch" >&2; exit 1 ;; esac

echo "Uploading patch..."
rsync -a -e "ssh -S $CTL" "$STAGE/" "$TARGET:$REMOTE_STAGE/"
echo "Applying on device..."
ssh -S "$CTL" "$TARGET" "sudo /usr/local/bin/piso-patch '$REMOTE_STAGE'"
ssh -S "$CTL" "$TARGET" "rm -rf '$REMOTE_STAGE'; tail -n 5 /var/log/piso-patch.log"
