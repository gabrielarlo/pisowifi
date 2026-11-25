#!/bin/sh
# Mirror authorized MACs from the app into the ipset, atomically.
# Also periodically fsync the DB WAL to SD so power-loss loses at most a few seconds.
set -e
n=0
while true; do
  macs=$(curl -sf --max-time 3 http://127.0.0.1:8000/api/internal/allowed-macs \
    | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin).get("macs", [])))' 2>/dev/null || true)
  ipset create pisowifi_allow_new hash:mac -exist
  ipset flush pisowifi_allow_new
  for mac in $macs; do
    ipset add pisowifi_allow_new "$mac" 2>/dev/null || true
  done
  ipset swap pisowifi_allow_new pisowifi_allow 2>/dev/null || true
  ipset destroy pisowifi_allow_new 2>/dev/null || true
  n=$((n+1))
  # Every ~30s (6×5s) checkpoint WAL and sync filesystem — keeps SD writes batched
  if [ $((n % 6)) -eq 0 ]; then
    python3 -c "import sqlite3; c=sqlite3.connect('/var/lib/pisowifi/pisowifi.db', timeout=2); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" 2>/dev/null || true
    sync 2>/dev/null || true
  fi
  sleep 5
done
