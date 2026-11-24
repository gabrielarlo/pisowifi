#!/bin/sh
# Guest VLAN gating. Idempotent: custom chains are flushed, jumps are added once.
set -e

ipset create pisowifi_allow hash:mac -exist
sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.ipv6.conf.guest0.disable_ipv6=1 >/dev/null

# --- NAT ---
iptables -t nat -N PISO_PRE 2>/dev/null || true
iptables -t nat -F PISO_PRE
iptables -t nat -C PREROUTING -i guest0 -j PISO_PRE 2>/dev/null || iptables -t nat -A PREROUTING -i guest0 -j PISO_PRE

# DNS hijack: only MACs NOT authorized get port 53 redirected to dnsmasq-portal
iptables -t nat -A PISO_PRE -i guest0 -p udp --dport 53 -m set ! --match-set pisowifi_allow src -j REDIRECT --to-ports 5353
iptables -t nat -A PISO_PRE -i guest0 -p tcp --dport 53 -m set ! --match-set pisowifi_allow src -j REDIRECT --to-ports 5353

# HTTP fallback: redirect unauthorized guests to the portal on this interface
iptables -t nat -A PISO_PRE -i guest0 -p tcp --dport 80 -m set ! --match-set pisowifi_allow src -j REDIRECT --to-ports 80

iptables -t nat -C POSTROUTING -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -j MASQUERADE

# --- FORWARD ---
iptables -N PISO_FWD 2>/dev/null || true
iptables -F PISO_FWD
iptables -C FORWARD -j PISO_FWD 2>/dev/null || iptables -A FORWARD -j PISO_FWD
iptables -A PISO_FWD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A PISO_FWD -i guest0 -m set --match-set pisowifi_allow src -j ACCEPT
iptables -A PISO_FWD -i guest0 -j DROP

# --- INPUT (defense in depth; policy stays ACCEPT) ---
iptables -C INPUT -i guest0 -p udp --dport 5353 -j ACCEPT 2>/dev/null || iptables -A INPUT -i guest0 -p udp --dport 5353 -j ACCEPT
iptables -C INPUT -i guest0 -p tcp --dport 5353 -j ACCEPT 2>/dev/null || iptables -A INPUT -i guest0 -p tcp --dport 5353 -j ACCEPT
iptables -C INPUT -i guest0 -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -A INPUT -i guest0 -p tcp --dport 80 -j ACCEPT
