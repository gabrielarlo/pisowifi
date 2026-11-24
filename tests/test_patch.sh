#!/bin/bash
# Local verification of piso-patch using stubbed systemctl/nginx/flock.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

R="$TMP/root"
mkdir -p "$R/opt/pisowifi/backend/app" "$R/opt/pisowifi/frontend/dist" \
         "$R/opt/pisowifi/venv/bin" "$R/etc/pisowifi" "$TMP/bin"

printf 'old nginx\n' > "$R/etc/pisowifi/nginx.conf"
printf 'old main\n' > "$R/opt/pisowifi/backend/app/main.py"

cat > "$TMP/bin/systemctl" <<'EOF'
#!/bin/bash
echo "systemctl $*" >> "$STUB_LOG"
exit "${STUB_SYSTEMCTL_RC:-0}"
EOF
cat > "$TMP/bin/nginx" <<'EOF'
#!/bin/bash
echo "nginx $*" >> "$STUB_LOG"
exit "${STUB_NGINX_RC:-0}"
EOF
cat > "$TMP/bin/dnsmasq" <<'EOF'
#!/bin/bash
echo "dnsmasq $*" >> "$STUB_LOG"
exit 0
EOF
cat > "$TMP/bin/flock" <<'EOF'
#!/bin/bash
exit 0
EOF
cat > "$R/opt/pisowifi/venv/bin/python" <<'EOF'
#!/bin/bash
exit "${STUB_PYTHON_RC:-0}"
EOF
chmod +x "$TMP/bin/"* "$R/opt/pisowifi/venv/bin/python"

cp "$ROOT/device/piso-patch" "$TMP/piso-patch"
chmod +x "$TMP/piso-patch"
export PISO_ROOT="$R" PISO_LOG="$TMP/log" PISO_BACKUP_ROOT="$TMP/backups" \
       PISO_VENV="$R/opt/pisowifi/venv" PISO_SYSTEMCTL="$TMP/bin/systemctl" \
       PISO_NGINX="$TMP/bin/nginx" PISO_LOCK="$TMP/lock" \
       PATH="$TMP/bin:$PATH" STUB_LOG="$TMP/stubs.log"

pass=0; fail=0
ok()   { echo "OK   $1"; pass=$((pass+1)); }
bad()  { echo "FAIL $1"; fail=$((fail+1)); }

# 1. allowlist rejection
S1="$TMP/s1"; mkdir -p "$S1/evil"; echo x > "$S1/evil/file"
if "$TMP/piso-patch" "$S1" >/dev/null 2>&1; then bad "allowlist rejection"; else ok "allowlist rejection"; fi
grep -q 'old nginx' "$R/etc/pisowifi/nginx.conf" && ok "no change on rejected patch" || bad "no change on rejected patch"

# 2. successful config patch + restart map
S2="$TMP/s2"; mkdir -p "$S2/device"; printf 'new nginx\n' > "$S2/device/nginx.conf"
if "$TMP/piso-patch" "$S2" >/dev/null 2>&1; then ok "successful patch"; else bad "successful patch"; fi
grep -q 'new nginx' "$R/etc/pisowifi/nginx.conf" && ok "config applied" || bad "config applied"
grep -q 'systemctl restart nginx' "$STUB_LOG" && ok "restart map (nginx)" || bad "restart map (nginx)"
grep -q 'OK: patch applied' "$PISO_LOG" && ok "success logged" || bad "success logged"

# 3. validation failure rolls back an overwritten file
export STUB_NGINX_RC=1
S3="$TMP/s3"; mkdir -p "$S3/device"; printf 'bad nginx\n' > "$S3/device/nginx.conf"
if "$TMP/piso-patch" "$S3" >/dev/null 2>&1; then bad "failure exits nonzero"; else ok "failure exits nonzero"; fi
grep -q 'new nginx' "$R/etc/pisowifi/nginx.conf" && ok "overwritten file restored" || bad "overwritten file restored"
grep -q 'ROLLBACK' "$PISO_LOG" && ok "rollback logged" || bad "rollback logged"

# 4. rollback deletes a newly added file
S4="$TMP/s4"; mkdir -p "$S4/device"
printf 'new sync\n' > "$S4/device/sync.sh"; printf 'bad nginx\n' > "$S4/device/nginx.conf"
"$TMP/piso-patch" "$S4" >/dev/null 2>&1 || true
[ ! -e "$R/etc/pisowifi/sync.sh" ] && ok "added file removed on rollback" || bad "added file removed on rollback"

unset STUB_NGINX_RC

# 5. SIGHUP (SSH disconnect) mid-patch triggers rollback
cat > "$TMP/bin/nginx" <<'EOF'
#!/bin/bash
echo "nginx $*" >> "$STUB_LOG"
sleep 3
exit 0
EOF
chmod +x "$TMP/bin/nginx"
S5="$TMP/s5"; mkdir -p "$S5/device"; printf 'hup nginx\n' > "$S5/device/nginx.conf"
"$TMP/piso-patch" "$S5" >/dev/null 2>&1 &
pid=$!
sleep 1
kill -HUP "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
grep -q 'new nginx' "$R/etc/pisowifi/nginx.conf" && ok "SIGHUP rollback restores file" || bad "SIGHUP rollback restores file"
grep -q 'INTERRUPTED' "$PISO_LOG" && ok "SIGHUP logged" || bad "SIGHUP logged"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
