#!/usr/bin/env bash
# Host-side wrapper: prepare wheels + frontend, then build the SD image in a
# privileged Debian container (loop devices + armhf binfmt required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
mkdir -p "$BUILD/wheels"

echo "[1/3] Downloading ARMv7 Python wheels..."
python3 -m pip download --quiet --only-binary=:all: \
  --platform manylinux_2_17_armv7l --python-version 3.13 \
  --implementation cp --abi cp313 \
  -d "$BUILD/wheels" fastapi uvicorn pydantic PyJWT

echo "[2/3] Building frontend..."
(cd "$ROOT/frontend" && npm install --no-audit --no-fund >/dev/null && npm run build)

echo "[3/3] Assembling image in privileged container..."
docker run --rm --privileged --userns=host \
  --dns 1.1.1.1 --dns 8.8.8.8 \
  -v "$ROOT:/work" -v "$BUILD:/build" \
  debian:trixie bash /work/scripts/build-image-in-docker.sh

echo "Done: $BUILD/pisowifi-opi-one.img"
if [ -f "$ROOT/secrets/ssh-credentials" ] && [ -f "$ROOT/secrets/admin-credentials" ]; then
  chmod 600 "$ROOT/secrets/ssh-credentials" "$ROOT/secrets/admin-credentials" 2>/dev/null || true
  echo "Secrets refreshed: $ROOT/secrets/ssh-credentials + $ROOT/secrets/admin-credentials (0600) — use for next flash/login"
fi
if [ -f "$BUILD/secrets/ssh-credentials" ]; then
  echo "Also copied to $BUILD/secrets/ + $BUILD/*.sha256"
fi
