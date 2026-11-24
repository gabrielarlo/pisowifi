import ipaddress
import re
import secrets
import subprocess
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import db
from .auth import decode_token, hash_password, make_token, verify_password
from .config import PIN_MAP

app = FastAPI(title="Piso WiFi clone")


@app.on_event("startup")
def startup():
    db.init_db()


def _parse_iso(value):
    return datetime.fromisoformat(value)


def neighbor_mac(ip: str, conn=None) -> str | None:
    """Resolve a client MAC from the kernel neighbor table. Fail closed."""
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    try:
        out = subprocess.run(
            ["ip", "neigh", "show", ip],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    for token in out.replace("lladdr", " ").split():
        if len(token) == 17 and token.count(":") == 5:
            if conn is not None:
                ap_mac = db.get_settings(conn).get("ap_mac", "").lower()
                if ap_mac and token.lower() == ap_mac:
                    return None  # AP in NAT/router mode: never bill its MAC
            return token.lower()
    return None


def client_mac(request, conn=None) -> str:
    """Derive MAC server-side. Dev-only X-Dev-Mac is honoured only in mock mode."""
    from .config import MOCK_MAC

    if MOCK_MAC:
        dev_mac = request.headers.get("x-dev-mac") or MOCK_MAC
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", dev_mac.lower()):
            raise HTTPException(400, "Invalid development MAC")
        return dev_mac.lower()
    ip = request.client.host if request.client else ""
    if ip in ("127.0.0.1", "::1", "testclient"):
        ip = request.headers.get("x-real-ip") or ip
    mac = neighbor_mac(ip, conn)
    if not mac:
        raise HTTPException(400, "Cannot determine client device — AP must be in bridge mode")
    return mac


def refresh_claim(conn, mac):
    from datetime import timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    conn.execute(
        "INSERT INTO coin_claims(mac,expires_at) VALUES (?,?) "
        "ON CONFLICT(mac) DO UPDATE SET expires_at=excluded.expires_at",
        (mac, expiry),
    )


def active_session_info(conn, mac):
    session = db.active_session(conn, mac)
    if not session:
        return None
    remaining = max(0, int((_parse_iso(session["expires_at"]) - datetime.now(timezone.utc)).total_seconds()))
    return {
        "id": session["id"],
        "active": remaining > 0,
        "remaining_seconds": remaining,
        "expires_at": session["expires_at"],
        "source": session["source"],
    }


def create_session(conn, mac, plan, source, ip=None):
    if db.active_session(conn, mac):
        raise HTTPException(409, "You already have an active session")
    conn.execute(
        "INSERT INTO sessions(mac,ip,plan_id,started_at,expires_at,source,active) VALUES (?,?,?,?,?,?,1)",
        (mac, ip, plan["id"], db.now_iso(), db.expiry_iso(plan["duration_minutes"]), source),
    )


def require_admin(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    username = decode_token(authorization.removeprefix("Bearer ").strip())
    if not username:
        raise HTTPException(401, "Invalid or expired token")
    conn = db.connect()
    user = conn.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return username


# ---------- Public portal ----------

@app.get("/api/portal/config")
def portal_config():
    conn = db.connect()
    settings = db.get_settings(conn)
    plans = [dict(r) for r in conn.execute("SELECT id,name,duration_minutes,coins_required,price FROM plans WHERE active=1 ORDER BY id")]
    conn.close()
    return {
        "hotspot_name": settings["hotspot_name"],
        "terms": settings["terms"],
        "currency": settings["currency"],
        "coin_value": settings["coin_value"],
        "plans": plans,
    }


@app.get("/api/portal/status")
def portal_status(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    with db.write_tx(conn):
        refresh_claim(conn, mac)
    result = {"mac": mac, "session": active_session_info(conn, mac)}
    conn.close()
    return result


@app.get("/api/portal/coins")
def portal_coins(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    with db.write_tx(conn):
        refresh_claim(conn, mac)
    row = conn.execute("SELECT coins FROM coin_balances WHERE mac=?", (mac,)).fetchone()
    events = [dict(r) for r in conn.execute(
        "SELECT id,delta,created_at FROM coin_events WHERE mac=? ORDER BY id DESC LIMIT 5", (mac,)
    )]
    conn.close()
    return {"mac": mac, "coins": row["coins"] if row else 0, "events": events}


class RedeemIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)


@app.post("/api/portal/redeem")
def portal_redeem(body: RedeemIn, request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    try:
        with db.write_tx(conn):
            voucher = conn.execute(
                "SELECT * FROM vouchers WHERE code=? AND status='unused'", (body.code.strip().upper(),)
            ).fetchone()
            if not voucher:
                raise HTTPException(400, "Invalid or already used voucher")
            matching = conn.execute(
                "SELECT id FROM plans WHERE duration_minutes=? ORDER BY id LIMIT 1",
                (voucher["duration_minutes"],),
            ).fetchone()
            plan_id = matching["id"] if matching else None
            plan = {"id": plan_id, "duration_minutes": voucher["duration_minutes"]}
            create_session(conn, mac, plan, "voucher")
            conn.execute(
                "UPDATE vouchers SET status='used',used_at=?,used_by_mac=? WHERE id=?",
                (db.now_iso(), mac, voucher["id"]),
            )
            conn.execute(
                "INSERT INTO transactions(mac,plan_id,amount,method,created_at) VALUES (?,?,?,?,?)",
                (mac, plan_id, voucher["price"], "voucher", db.now_iso()),
            )
    finally:
        conn.close()
    read = db.connect()
    result = {"ok": True, "session": active_session_info(read, mac)}
    read.close()
    return result


class PurchaseIn(BaseModel):
    plan_id: int


@app.post("/api/portal/purchase")
def portal_purchase(body: PurchaseIn, request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    try:
        with db.write_tx(conn):
            plan = conn.execute("SELECT * FROM plans WHERE id=? AND active=1", (body.plan_id,)).fetchone()
            if not plan:
                raise HTTPException(404, "Plan not found")
            balance_row = conn.execute("SELECT coins FROM coin_balances WHERE mac=?", (mac,)).fetchone()
            balance = balance_row["coins"] if balance_row else 0
            if balance < plan["coins_required"]:
                raise HTTPException(402, f"Need {plan['coins_required']} coin(s), you have {balance}")
            conn.execute(
                "UPDATE coin_balances SET coins=coins-? WHERE mac=?", (plan["coins_required"], mac)
            )
            conn.execute(
                "INSERT INTO coin_events(mac,delta,created_at) VALUES (?,?,?)",
                (mac, -plan["coins_required"], db.now_iso()),
            )
            create_session(conn, mac, plan, "coin", ip)
            conn.execute(
                "INSERT INTO transactions(mac,plan_id,amount,method,created_at) VALUES (?,?,?,?,?)",
                (mac, plan["id"], plan["price"], "coin", db.now_iso()),
            )
    finally:
        conn.close()
    read = db.connect()
    result = {"ok": True, "session": active_session_info(read, mac)}
    read.close()
    return result


@app.post("/api/portal/logout")
def portal_logout(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    with db.write_tx(conn):
        conn.execute(
            "UPDATE sessions SET active=0,ended_at=? WHERE mac=? AND active=1", (db.now_iso(), mac)
        )
    conn.close()
    return {"ok": True}


# ---------- Auth + admin ----------

class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn):
    conn = db.connect()
    user = conn.execute("SELECT * FROM admin_users WHERE username=?", (body.username,)).fetchone()
    conn.close()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": make_token(body.username), "username": body.username}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


@app.post("/api/auth/change-password")
def change_password(body: PasswordIn, username: str = Depends(require_admin)):
    conn = db.connect()
    user = conn.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
    if not user or not verify_password(body.old_password, user["password_hash"]):
        conn.close()
        raise HTTPException(400, "Current password is incorrect")
    with db.write_tx(conn):
        conn.execute(
            "UPDATE admin_users SET password_hash=? WHERE username=?",
            (hash_password(body.new_password), username),
        )
    conn.close()
    return {"ok": True}


@app.get("/api/admin/overview")
def overview(username: str = Depends(require_admin)):
    conn = db.connect()
    today = db.now_iso()[:10]
    active = len(db.allowed_macs(conn))
    revenue = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM transactions WHERE created_at LIKE ?", (today + "%",)
    ).fetchone()["total"]
    vouchers = conn.execute("SELECT COUNT(*) AS n FROM vouchers WHERE status='used'").fetchone()["n"]
    coins = conn.execute("SELECT COALESCE(SUM(coins),0) AS n FROM coin_balances").fetchone()["n"]
    conn.close()
    return {"active_clients": active, "revenue_today": revenue, "vouchers_used": vouchers, "coins_outstanding": coins}


@app.get("/api/admin/vouchers")
def list_vouchers(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM vouchers ORDER BY id DESC LIMIT 200")]
    conn.close()
    return rows


class VoucherGenIn(BaseModel):
    count: int = Field(ge=1, le=100)
    duration_minutes: int = Field(ge=1)
    price: float = Field(ge=0)


@app.post("/api/admin/vouchers/generate")
def generate_vouchers(body: VoucherGenIn, username: str = Depends(require_admin)):
    conn = db.connect()
    codes = []
    with db.write_tx(conn):
        for _ in range(body.count):
            code = secrets.token_hex(4).upper()
            while conn.execute("SELECT 1 FROM vouchers WHERE code=?", (code,)).fetchone():
                code = secrets.token_hex(4).upper()
            conn.execute(
                "INSERT INTO vouchers(code,duration_minutes,price,created_at) VALUES (?,?,?,?)",
                (code, body.duration_minutes, body.price, db.now_iso()),
            )
            codes.append(code)
    conn.close()
    return {"codes": codes}


@app.delete("/api/admin/vouchers/{voucher_id}")
def delete_voucher(voucher_id: int, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute("DELETE FROM vouchers WHERE id=? AND status='unused'", (voucher_id,))
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Unused voucher not found")
    return {"ok": True}


@app.get("/api/admin/sessions")
def list_sessions(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT id,mac,ip,started_at,expires_at,source,active,ended_at FROM sessions ORDER BY id DESC LIMIT 200"
    )]
    conn.close()
    for row in rows:
        row["active"] = bool(row["active"] and row["expires_at"] > db.now_iso())
    return rows


@app.post("/api/admin/sessions/{session_id}/revoke")
def revoke_session(session_id: int, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute(
            "UPDATE sessions SET active=0,ended_at=? WHERE id=? AND active=1", (db.now_iso(), session_id)
        )
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Active session not found")
    return {"ok": True}


@app.get("/api/admin/transactions")
def list_transactions(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 200")]
    conn.close()
    return rows


@app.get("/api/admin/plans")
def list_plans(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM plans ORDER BY id")]
    conn.close()
    return rows


class PlanIn(BaseModel):
    name: str
    duration_minutes: int = Field(ge=1)
    coins_required: int = Field(ge=1)
    price: float = Field(ge=0)
    active: bool = True


@app.post("/api/admin/plans")
def add_plan(body: PlanIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute(
            "INSERT INTO plans(name,duration_minutes,coins_required,price,active) VALUES (?,?,?,?,?)",
            (body.name, body.duration_minutes, body.coins_required, body.price, int(body.active)),
        )
        plan_id = cur.lastrowid
    conn.close()
    return {"id": plan_id}


@app.put("/api/admin/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute(
            "UPDATE plans SET name=?,duration_minutes=?,coins_required=?,price=?,active=? WHERE id=?",
            (body.name, body.duration_minutes, body.coins_required, body.price, int(body.active), plan_id),
        )
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Plan not found")
    return {"ok": True}


@app.delete("/api/admin/plans/{plan_id}")
def delete_plan(plan_id: int, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute("DELETE FROM plans WHERE id=?", (plan_id,))
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Plan not found")
    return {"ok": True}


@app.get("/api/admin/settings")
def get_all_settings(username: str = Depends(require_admin)):
    conn = db.connect()
    settings = db.get_settings(conn)
    conn.close()
    return settings


class SettingsIn(BaseModel):
    hotspot_name: str | None = None
    terms: str | None = None
    currency: str | None = None
    coin_value: str | None = None


@app.put("/api/admin/settings")
def put_settings(body: SettingsIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        for key, value in body.model_dump(exclude_none=True).items():
            db.set_setting(conn, key, value)
    conn.close()
    return {"ok": True}


@app.get("/api/admin/hardware")
def get_hardware(username: str = Depends(require_admin)):
    conn = db.connect()
    settings = db.get_settings(conn)
    conn.close()
    return {
        "coin_pulse_pin": int(settings["coin_pulse_pin"]),
        "relay_pin": int(settings["relay_pin"]),
        "gpio_enabled": settings["gpio_enabled"] == "1",
        "relay_active": settings["relay_active"] == "1",
        "pin_map": {str(k): list(v) for k, v in PIN_MAP.items()},
    }


class HardwareIn(BaseModel):
    coin_pulse_pin: int
    relay_pin: int
    gpio_enabled: bool = False
    relay_active: bool = False


def apply_relay(pin: int, active: bool):
    """Set the inhibit relay; no-op in host/mock mode."""
    from .config import GPIO_ENABLED

    if not GPIO_ENABLED:
        return
    chip, offset = PIN_MAP[pin]
    subprocess.run(["gpioset", chip, f"{offset}={1 if active else 0}"], check=False, timeout=5)


@app.put("/api/admin/hardware")
def put_hardware(body: HardwareIn, username: str = Depends(require_admin)):
    if body.coin_pulse_pin not in PIN_MAP or body.relay_pin not in PIN_MAP:
        raise HTTPException(400, "Unsupported physical pin (use 3, 5 or 11)")
    apply_relay(body.relay_pin, body.relay_active)
    conn = db.connect()
    with db.write_tx(conn):
        db.set_setting(conn, "coin_pulse_pin", body.coin_pulse_pin)
        db.set_setting(conn, "relay_pin", body.relay_pin)
        db.set_setting(conn, "gpio_enabled", int(body.gpio_enabled))
        db.set_setting(conn, "relay_active", int(body.relay_active))
    conn.close()
    return {"ok": True}


@app.get("/api/admin/coins")
def list_coin_events(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM coin_events ORDER BY id DESC LIMIT 100")]
    conn.close()
    return rows


# ---------- Internal (loopback only on device) ----------

@app.get("/api/internal/allowed-macs")
def allowed():
    conn = db.connect()
    macs = db.allowed_macs(conn)
    conn.close()
    return {"macs": macs}


@app.get("/api/internal/resolve-mac")
def resolve_mac_endpoint(ip: str):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, "Invalid IP address")
    conn = db.connect()
    mac = neighbor_mac(ip, conn)
    conn.close()
    return {"mac": mac}


class PulseIn(BaseModel):
    value: int = Field(default=1, ge=1)


@app.post("/api/internal/coin-pulse")
def coin_pulse(body: PulseIn):
    conn = db.connect()
    with db.write_tx(conn):
        claim = conn.execute(
            "SELECT mac FROM coin_claims WHERE expires_at>? ORDER BY expires_at DESC LIMIT 1",
            (db.now_iso(),),
        ).fetchone()
        mac = claim["mac"] if claim else None
        conn.execute(
            "INSERT INTO coin_events(mac,delta,created_at) VALUES (?,?,?)",
            (mac, body.value, db.now_iso()),
        )
        if mac:
            conn.execute(
                "INSERT INTO coin_balances(mac,coins) VALUES (?,?) "
                "ON CONFLICT(mac) DO UPDATE SET coins=coins+excluded.coins",
                (mac, body.value),
            )
    conn.close()
    return {"credited": mac, "coins": body.value}
