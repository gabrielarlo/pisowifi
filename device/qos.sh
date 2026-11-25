#!/bin/sh
# Apply QoS shaping on guest0 from /api/internal/qos-clients.
# All guests share global bandwidth (320 Mbps default, admin-managed) and each guest
# gets its own isolated 10 Mbps leaf (or per-plan override). Uses tc htb per-IP.
# Polls every 10s, idempotent, fully dynamic: classes follow active sessions.
set -e
IFACE="${PISO_IFACE:-guest0}"
API_QOS_CLIENTS="http://127.0.0.1:8000/api/internal/qos-clients"
LAST=""

apply_qos() {
  json="$1"
  enabled=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("qos",{}).get("qos_enabled",True)).lower())' 2>/dev/null || echo "true")
  down_global=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("qos",{}).get("qos_global_down_mbps",320))' 2>/dev/null || echo 320)
  up_global=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("qos",{}).get("qos_global_up_mbps",320))' 2>/dev/null || echo 320)
  # Fallback per-guest defaults (used for the default/unclassified class)
  down_guest_def=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("qos",{}).get("qos_per_guest_down_mbps",10))' 2>/dev/null || echo 10)
  up_guest_def=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("qos",{}).get("qos_per_guest_up_mbps",10))' 2>/dev/null || echo 10)

  echo "$down_global $up_global $down_guest_def $up_guest_def" | grep -Eq '^[0-9]+ [0-9]+ [0-9]+ [0-9]+$' || return 0

  if [ "$enabled" != "true" ]; then
    tc qdisc del dev "$IFACE" root 2>/dev/null || true
    tc qdisc del dev "$IFACE" ingress 2>/dev/null || true
    tc qdisc del dev ifb0 root 2>/dev/null || true
    ip link set ifb0 down 2>/dev/null || true
    return 0
  fi

  # Extract clients as lines "ip down up" (only clients with IP 10.0.0.x)
  clients=$(printf '%s' "$json" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
    for c in d.get("clients",[]):
        ip=c.get("ip")
        if not ip: continue
        # only shape guest subnet
        if not ip.startswith("10.0.0."): continue
        try:
            last=int(ip.split(".")[-1])
            if last < 2 or last > 254: continue
        except: continue
        down=c.get("down_mbps",10)
        up=c.get("up_mbps",10)
        print(f"{ip} {down} {up} {last}")
except Exception:
    pass
' 2>/dev/null || true)

  # Ingress redirect via IFB (upload shaping)
  modprobe ifb numifbs=1 2>/dev/null || true
  ip link set ifb0 up 2>/dev/null || true
  tc qdisc del dev "$IFACE" ingress 2>/dev/null || true
  tc qdisc add dev "$IFACE" ingress 2>/dev/null || true
  tc filter del dev "$IFACE" parent ffff: 2>/dev/null || true
  tc filter add dev "$IFACE" parent ffff: protocol ip u32 match u32 0 0 flowid 1:1 action mirred egress redirect dev ifb0 2>/dev/null || true

  # Egress (download): guest0 -> guests
  tc qdisc del dev "$IFACE" root 2>/dev/null || true
  tc qdisc add dev "$IFACE" root handle 1: htb default 999 2>/dev/null || true
  tc class add dev "$IFACE" parent 1: classid 1:1 htb rate "${down_global}mbit" ceil "${down_global}mbit" 2>/dev/null || true
  # default class for unclassified / not-yet-shaped IPs (per-guest cap)
  tc class add dev "$IFACE" parent 1:1 classid 1:999 htb rate "${down_guest_def}mbit" ceil "${down_guest_def}mbit" 2>/dev/null || true
  tc qdisc add dev "$IFACE" parent 1:999 handle 999: sfq perturb 10 2>/dev/null || true

  # Ingress (upload) via IFB: guests -> internet
  tc qdisc del dev ifb0 root 2>/dev/null || true
  tc qdisc add dev ifb0 root handle 2: htb default 999 2>/dev/null || true
  tc class add dev ifb0 parent 2: classid 2:1 htb rate "${up_global}mbit" ceil "${up_global}mbit" 2>/dev/null || true
  tc class add dev ifb0 parent 2:1 classid 2:999 htb rate "${up_guest_def}mbit" ceil "${up_guest_def}mbit" 2>/dev/null || true
  tc qdisc add dev ifb0 parent 2:999 handle 2999: sfq perturb 10 2>/dev/null || true

  # Per-IP leaves - each guest gets its own 10 Mbps (or per-plan override) leaf under the shared global parent
  echo "$clients" | while read -r ip down up last; do
    [ -z "$ip" ] && continue
    # Validate numeric rates
    echo "$down $up $last" | grep -Eq '^[0-9]+ [0-9]+ [0-9]+$' || continue
    # download leaf
    tc class add dev "$IFACE" parent 1:1 classid "1:$last" htb rate "${down}mbit" ceil "${down}mbit" 2>/dev/null || true
    tc qdisc add dev "$IFACE" parent "1:$last" handle "$last:" sfq perturb 10 2>/dev/null || true
    tc filter add dev "$IFACE" protocol ip parent 1:0 prio 1 u32 match ip dst "$ip" flowid "1:$last" 2>/dev/null || true
    # upload leaf
    tc class add dev ifb0 parent 2:1 classid "2:$last" htb rate "${up}mbit" ceil "${up}mbit" 2>/dev/null || true
    tc qdisc add dev ifb0 parent "2:$last" handle "2${last}:" sfq perturb 10 2>/dev/null || true
    tc filter add dev ifb0 protocol ip parent 2:0 prio 1 u32 match ip src "$ip" flowid "2:$last" 2>/dev/null || true
  done
}

while true; do
  # ARP keepalive: refresh neighbour entries for all DHCP leases so portal's
  # `ip neigh show <guest-ip>` stays REACHABLE and `client_mac` doesn't fail
  # with "AP must be in bridge mode" after STALE/FAILED.
  for _ip in $(cat /var/lib/misc/dnsmasq.leases 2>/dev/null | awk '{print $3}'); do
    _mac=$(awk -v ip="$_ip" '$3==ip {print $2}' /var/lib/misc/dnsmasq.leases 2>/dev/null | head -1)
    if [ -n "$_mac" ]; then
      ip neigh replace "$_ip" lladdr "$_mac" dev guest0 nud reachable 2>/dev/null || true
    fi
    ping -c1 -W1 -I guest0 "$_ip" >/dev/null 2>&1 || true
    arping -c1 -I guest0 "$_ip" >/dev/null 2>&1 || true
  done
  json=$(curl -sf --max-time 3 "$API_QOS_CLIENTS" 2>/dev/null || echo "")
  # Fallback to legacy qos endpoint if new one not present (older image)
  if [ -z "$json" ] || ! printf '%s' "$json" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
    json=$(curl -sf --max-time 3 "http://127.0.0.1:8000/api/internal/qos" 2>/dev/null || echo "")
    # Wrap legacy into new shape so apply_qos still works
    if [ -n "$json" ]; then
      json=$(printf '%s' "$json" | python3 -c 'import json,sys; q=json.load(sys.stdin); print(json.dumps({"qos":q,"clients":[]}))' 2>/dev/null || echo "")
    fi
  fi
  if [ -n "$json" ]; then
    cur=$(printf '%s' "$json" | tr -d ' \n' | md5sum 2>/dev/null | awk '{print $1}')
    [ -z "$cur" ] && cur=$(printf '%s' "$json" | python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.read().encode()).hexdigest())' 2>/dev/null || echo "")
    if [ "$cur" != "$LAST" ]; then
      apply_qos "$json" || true
      LAST="$cur"
    fi
  fi
  sleep 10
done
