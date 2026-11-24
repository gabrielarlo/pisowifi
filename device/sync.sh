#!/bin/sh
# Mirror authorized MACs from the app into the ipset, atomically.
set -e
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
  sleep 5
done
