import ipaddress
import re
import secrets
import subprocess
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db
from .auth import decode_token, hash_password, make_token, verify_password
from .config import PIN_MAP, image_version

app = FastAPI(title="Piso WiFi clone")





def _session_pause_enabled(conn):
    try:
        return conn.execute("SELECT value FROM settings WHERE key='session_pause_enabled'").fetchone()[0] != "0"
    except Exception:
        return True


@app.on_event("startup")
def startup():
    db.init_db()
    # Background watcher: pause when device disconnects from AP (no heartbeat),
    # auto-resume is handled on next portal/status poll via heartbeat_and_maybe_resume.
    import threading
    import time

    def _watch_disconnects():
        while True:
            time.sleep(30)
            try:
                conn2 = db.connect()
                if not _session_pause_enabled(conn2):
                    conn2.close()
                    continue
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
                rows = conn2.execute(
                    "SELECT * FROM sessions WHERE active=1 AND paused=0 AND last_seen IS NOT NULL AND last_seen<? AND expires_at>?", (cutoff, db.now_iso())
                ).fetchall()
                if rows:
                    with db.write_tx(conn2):
                        for r in rows:
                            db.pause_session(conn2, r)
                conn2.close()
            except Exception:
                try:
                    conn2.close()
                except Exception:
                    pass

    threading.Thread(target=_watch_disconnects, daemon=True).start()


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
    # Fallback: if ip neigh is FAILED/STALE, read directly from dnsmasq leases (bridge mode)
    try:
        with open("/var/lib/misc/dnsmasq.leases") as _f:
            for _line in _f:
                _parts = _line.split()
                if len(_parts) >= 3 and _parts[2] == ip:
                    _mac = _parts[1].lower()
                    if len(_mac) == 17 and _mac.count(":") == 5:
                        if conn is not None:
                            ap_mac2 = db.get_settings(conn).get("ap_mac", "").lower()
                            if ap_mac2 and _mac == ap_mac2:
                                return None
                        return _mac
    except Exception:
        pass
    return None


def client_mac(request, conn=None) -> str:
    """Derive MAC server-side. Dev-only X-Dev-Mac is honoured only in mock mode."""
    from .config import MOCK_MAC

    if MOCK_MAC:
        dev_mac = request.headers.get("x-dev-mac") or MOCK_MAC
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", dev_mac.lower()):
            raise HTTPException(400, "Invalid development MAC")
        return dev_mac.lower()
    # Prefer X-Real-IP from nginx (guest 10.0.0.1/captive.apple.com → 127.0.0.1:8000)
    # Only trust the header when the immediate peer is loopback (nginx on device).
    # Otherwise a guest could spoof it if backend were ever exposed.
    client_host = request.client.host if request.client else ""
    hdr = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP")
    if hdr and client_host in ("127.0.0.1", "::1", "testclient"):
        ip = hdr
    else:
        ip = client_host
    mac = neighbor_mac(ip, conn)
    if not mac:
        raise HTTPException(400, "Cannot determine client device — AP must be in bridge mode")
    return mac


def refresh_claim(conn, mac):
    # Deprecated: kept for backwards compat. Coin inserts now require explicit
    # POST /api/portal/coin-start with a short window (coin_countdown). Do not
    # auto-claim on status/coins polling or the slot would accept coins idle.
    pass


def start_coin_claim(conn, mac):
    from datetime import timedelta
    # Active Insert Coin window — only during this claim will coin-pulse be credited.
    raw = conn.execute("SELECT value FROM settings WHERE key='coin_countdown'").fetchone()
    try:
        seconds = int(raw[0]) if raw and raw[0] else 60
    except ValueError:
        seconds = 60
    seconds = max(5, min(120, seconds))
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    conn.execute(
        "INSERT INTO coin_claims(mac,expires_at) VALUES (?,?) "
        "ON CONFLICT(mac) DO UPDATE SET expires_at=excluded.expires_at",
        (mac, expiry),
    )
    return seconds


def extend_coin_claim(conn, mac):
    from datetime import timedelta
    raw = conn.execute("SELECT value FROM settings WHERE key='coin_countdown'").fetchone()
    try:
        seconds = int(raw[0]) if raw and raw[0] else 60
    except ValueError:
        seconds = 60
    seconds = max(5, min(120, seconds))
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    conn.execute("UPDATE coin_claims SET expires_at=? WHERE mac=?", (expiry, mac))
    return seconds


def active_session_info(conn, mac):
    session = db.active_session(conn, mac)
    if not session:
        return None
    if session["paused"]:
        remaining = int(session["paused_remaining"] or 0)
        return {
            "id": session["id"],
            "active": remaining > 0,
            "remaining_seconds": remaining,
            "expires_at": session["expires_at"],
            "source": session["source"],
            "paused": True,
            "paused_remaining": remaining,
        }
    remaining = max(0, int((_parse_iso(session["expires_at"]) - datetime.now(timezone.utc)).total_seconds()))
    if remaining <= 0:
        return None
    return {
        "id": session["id"],
        "active": remaining > 0,
        "remaining_seconds": remaining,
        "expires_at": session["expires_at"],
        "source": session["source"],
        "paused": False,
    }


def create_session(conn, mac, plan, source, ip=None):
    if db.active_session(conn, mac):
        raise HTTPException(409, "You already have an active session")
    now = db.now_iso()
    conn.execute(
        "INSERT INTO sessions(mac,ip,plan_id,started_at,expires_at,source,active,last_seen) VALUES (?,?,?,?,?,?,1,?)",
        (mac, ip, plan["id"], now, db.expiry_iso(plan["duration_minutes"]), source, now),
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
        "coin_countdown": int(settings.get("coin_countdown", "60") or 60),
        "banner_subtitle": settings.get("banner_subtitle", "Pay as you go internet"),
        "banner_bg": settings.get("banner_bg", "#1d4ed8"),
        "banner_fg": settings.get("banner_fg", "#ffffff"),
        "plans": plans,
    }


@app.get("/api/portal/status")
def portal_status(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    ip = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP") or (request.client.host if request.client else None)
    # Heartbeat: if session was paused (power loss or AP disconnect), resume on reconnect
    with db.write_tx(conn):
        db.track_device(conn, mac, ip)
        db.heartbeat_and_maybe_resume(conn, mac)
    result = {"mac": mac, "session": active_session_info(conn, mac)}
    conn.close()
    return result


@app.get("/api/portal/coins")
def portal_coins(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    ip = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP") or (request.client.host if request.client else None)
    with db.write_tx(conn):
        db.track_device(conn, mac, ip)
        db.heartbeat_and_maybe_resume(conn, mac)
    row = conn.execute("SELECT coins FROM coin_balances WHERE mac=?", (mac,)).fetchone()
    events = [dict(r) for r in conn.execute(
        "SELECT id,delta,created_at FROM coin_events WHERE mac=? ORDER BY id DESC LIMIT 5", (mac,)
    )]
    conn.close()
    return {"mac": mac, "coins": row["coins"] if row else 0, "events": events}


@app.post("/api/portal/coin-start")
def portal_coin_start(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    with db.write_tx(conn):
        seconds = start_coin_claim(conn, mac)
    conn.close()
    return {"ok": True, "mac": mac, "window_seconds": seconds}


@app.post("/api/portal/coin-stop")
def portal_coin_stop(request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    with db.write_tx(conn):
        conn.execute("DELETE FROM coin_claims WHERE mac=?", (mac,))
    conn.close()
    return {"ok": True}


class RedeemIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)


@app.post("/api/portal/redeem")
def portal_redeem(body: RedeemIn, request: Request):
    conn = db.connect()
    mac = client_mac(request, conn)
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
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
            create_session(conn, mac, plan, "voucher", ip)
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
    new_password: str | None = Field(default=None, min_length=6)
    new_password_confirm: str | None = None
    new_username: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9._-]+$")


@app.get("/api/admin/password-status")
def password_status(username: str = Depends(require_admin)):
    conn = db.connect()
    user = conn.execute("SELECT password_hash FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    is_default = False
    if user:
        try:
            is_default = verify_password("admin@123", user["password_hash"])
        except Exception:
            pass
    return {"is_default": is_default, "username": username}


@app.get("/api/admin/version")
def admin_version(username: str = Depends(require_admin)):
    return {"version": image_version()}


@app.post("/api/auth/change-password")
def change_password(body: PasswordIn, username: str = Depends(require_admin)):
    # At least one change required
    if not body.new_password and not body.new_username:
        raise HTTPException(400, "Provide a new username or new password")
    if body.new_password and body.new_password_confirm is not None and body.new_password != body.new_password_confirm:
        raise HTTPException(400, "New passwords do not match")
    if body.new_username and body.new_username == username and not body.new_password:
        raise HTTPException(400, "No changes to save")
    conn = db.connect()
    user = conn.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
    if not user or not verify_password(body.old_password, user["password_hash"]):
        conn.close()
        raise HTTPException(400, "Current password is incorrect")
    new_username = body.new_username.strip() if body.new_username else None
    if new_username and new_username != username:
        if conn.execute("SELECT 1 FROM admin_users WHERE username=?", (new_username,)).fetchone():
            conn.close()
            raise HTTPException(409, "Username already taken")
    with db.write_tx(conn):
        target = username
        if new_username and new_username != username:
            conn.execute("UPDATE admin_users SET username=? WHERE username=?", (new_username, username))
            target = new_username
        if body.new_password:
            conn.execute(
                "UPDATE admin_users SET password_hash=? WHERE username=?",
                (hash_password(body.new_password), target),
            )
    conn.close()
    # Issue fresh token if username changed so client can stay logged in
    resp = {"ok": True}
    if new_username and new_username != username:
        resp["username"] = new_username
        resp["token"] = make_token(new_username)
    return resp


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
    guests_total = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
    conn.close()
    return {"active_clients": active, "revenue_today": revenue, "vouchers_used": vouchers, "coins_outstanding": coins, "guests_total": guests_total}


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


@app.get("/api/admin/devices")
def list_devices(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT mac,ip,first_seen,last_seen,hits FROM devices ORDER BY last_seen DESC LIMIT 200"
    )]
    conn.close()
    return rows


@app.get("/api/admin/sessions")
def list_sessions(username: str = Depends(require_admin)):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT id,mac,ip,started_at,expires_at,source,active,ended_at,paused,paused_remaining,paused_at,last_seen FROM sessions ORDER BY id DESC LIMIT 200"
    )]
    conn.close()
    for row in rows:
        # Paused = has remaining but not currently allowed through firewall
        if row.get("paused"):
            row["active"] = bool(row["active"] and (row["paused_remaining"] or 0) > 0)
        else:
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
    qos_down_mbps: int | None = Field(default=None, ge=1, le=1000)
    qos_up_mbps: int | None = Field(default=None, ge=1, le=1000)


@app.post("/api/admin/plans")
def add_plan(body: PlanIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute(
            "INSERT INTO plans(name,duration_minutes,coins_required,price,active,qos_down_mbps,qos_up_mbps) VALUES (?,?,?,?,?,?,?)",
            (body.name, body.duration_minutes, body.coins_required, body.price, int(body.active), body.qos_down_mbps, body.qos_up_mbps),
        )
        plan_id = cur.lastrowid
    conn.close()
    return {"id": plan_id}


@app.put("/api/admin/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        cur = conn.execute(
            "UPDATE plans SET name=?,duration_minutes=?,coins_required=?,price=?,active=?,qos_down_mbps=?,qos_up_mbps=? WHERE id=?",
            (body.name, body.duration_minutes, body.coins_required, body.price, int(body.active), body.qos_down_mbps, body.qos_up_mbps, plan_id),
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
    coin_countdown: int | None = Field(default=None, ge=5, le=120)
    banner_subtitle: str | None = None
    banner_bg: str | None = None
    banner_fg: str | None = None
    session_pause_enabled: str | int | bool | None = None


@app.put("/api/admin/settings")
def put_settings(body: SettingsIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        for key, value in body.model_dump(exclude_none=True).items():
            if key == "session_pause_enabled":
                # Normalize bool/int/str -> "1"/"0"
                if isinstance(value, bool):
                    v = "1" if value else "0"
                elif isinstance(value, int):
                    v = "1" if value else "0"
                else:
                    v = "1" if str(value) in ("1", "true", "True") else "0"
                db.set_setting(conn, key, v)
            else:
                db.set_setting(conn, key, value)
    conn.close()
    return {"ok": True}


def _qos_from_settings(settings: dict) -> dict:
    def _int(key: str, default: int) -> int:
        try:
            return int(settings.get(key, default))
        except (ValueError, TypeError):
            return default
    return {
        "qos_enabled": settings.get("qos_enabled", "1") == "1",
        "qos_per_guest_down_mbps": max(1, min(1000, _int("qos_per_guest_down_mbps", 10))),
        "qos_per_guest_up_mbps": max(1, min(1000, _int("qos_per_guest_up_mbps", 10))),
        "qos_global_down_mbps": max(1, min(10000, _int("qos_global_down_mbps", 320))),
        "qos_global_up_mbps": max(1, min(10000, _int("qos_global_up_mbps", 320))),
    }


@app.get("/api/admin/qos")
def get_qos(username: str = Depends(require_admin)):
    conn = db.connect()
    settings = db.get_settings(conn)
    conn.close()
    return _qos_from_settings(settings)


class QosIn(BaseModel):
    qos_enabled: bool = True
    qos_per_guest_down_mbps: int = Field(ge=1, le=1000)
    qos_per_guest_up_mbps: int = Field(ge=1, le=1000)
    qos_global_down_mbps: int = Field(ge=1, le=10000)
    qos_global_up_mbps: int = Field(ge=1, le=10000)


@app.put("/api/admin/qos")
def put_qos(body: QosIn, username: str = Depends(require_admin)):
    conn = db.connect()
    with db.write_tx(conn):
        db.set_setting(conn, "qos_enabled", int(body.qos_enabled))
        db.set_setting(conn, "qos_per_guest_down_mbps", body.qos_per_guest_down_mbps)
        db.set_setting(conn, "qos_per_guest_up_mbps", body.qos_per_guest_up_mbps)
        db.set_setting(conn, "qos_global_down_mbps", body.qos_global_down_mbps)
        db.set_setting(conn, "qos_global_up_mbps", body.qos_global_up_mbps)
    conn.close()
    return {"ok": True}


@app.get("/api/internal/qos")
def internal_qos():
    conn = db.connect()
    settings = db.get_settings(conn)
    conn.close()
    return _qos_from_settings(settings)


def _qos_clients_payload(conn):
    settings = db.get_settings(conn)
    qos = _qos_from_settings(settings)
    # active sessions with IP for shaping; paused sessions still occupy bandwidth reservation but not active TX
    rows = conn.execute(
        "SELECT s.mac, s.ip, s.plan_id, p.qos_down_mbps, p.qos_up_mbps "
        "FROM sessions s LEFT JOIN plans p ON s.plan_id=p.id "
        "WHERE s.active=1 AND s.paused=0 AND s.expires_at>?",
        (db.now_iso(),),
    ).fetchall()
    clients = []
    for r in rows:
        # Per-plan override if set, else per-guest default
        down = r["qos_down_mbps"] if r["qos_down_mbps"] is not None else qos["qos_per_guest_down_mbps"]
        up = r["qos_up_mbps"] if r["qos_up_mbps"] is not None else qos["qos_per_guest_up_mbps"]
        # Clamp
        try:
            down = max(1, min(1000, int(down)))
            up = max(1, min(1000, int(up)))
        except Exception:
            down = qos["qos_per_guest_down_mbps"]
            up = qos["qos_per_guest_up_mbps"]
        # Only shape clients with a valid guest IP (10.0.0.0/24); others still counted but qos.sh will ignore IP-less
        clients.append({
            "mac": r["mac"],
            "ip": r["ip"],
            "plan_id": r["plan_id"],
            "down_mbps": down,
            "up_mbps": up,
        })
    return {"qos": qos, "clients": clients}


@app.get("/api/internal/qos-clients")
def internal_qos_clients():
    conn = db.connect()
    payload = _qos_clients_payload(conn)
    conn.close()
    return payload


@app.get("/api/admin/qos/clients")
def admin_qos_clients(username: str = Depends(require_admin)):
    conn = db.connect()
    payload = _qos_clients_payload(conn)
    conn.close()
    return payload


@app.get("/api/admin/qos/history")
def admin_qos_history(username: str = Depends(require_admin), limit: int = 100):
    limit = max(1, min(500, limit))
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM bandwidth_samples ORDER BY id DESC LIMIT ?", (limit,)
    )]
    conn.close()
    return rows


class BandwidthReportIn(BaseModel):
    mac: str | None = None
    ip: str | None = None
    rx_bytes: int = Field(ge=0)
    tx_bytes: int = Field(ge=0)


@app.post("/api/internal/bandwidth-report")
def internal_bandwidth_report(body: BandwidthReportIn):
    # Device-side qos.sh can POST periodic tc counters here (loopback only on device; open in dev)
    conn = db.connect()
    with db.write_tx(conn):
        conn.execute(
            "INSERT INTO bandwidth_samples(mac,ip,rx_bytes,tx_bytes,recorded_at) VALUES (?,?,?,?,?)",
            (body.mac, body.ip, body.rx_bytes, body.tx_bytes, db.now_iso()),
        )
        # Keep only last 5000 samples to bound DB
        conn.execute("DELETE FROM bandwidth_samples WHERE id NOT IN (SELECT id FROM bandwidth_samples ORDER BY id DESC LIMIT 5000)")
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


# ---------- Backup & Restore ----------
BACKUP_TABLES = [
    "settings",
    "admin_users",
    "plans",
    "vouchers",
    "sessions",
    "devices",
    "transactions",
    "coin_events",
    "coin_balances",
    "coin_claims",
    "bandwidth_samples",
]


@app.get("/api/admin/backup")
def admin_backup(username: str = Depends(require_admin)):
    conn = db.connect()
    payload = {"meta": {"version": 1, "created_at": db.now_iso()}, "tables": {}}
    for tbl in BACKUP_TABLES:
        try:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {tbl}")]  # noqa: S608 safe — tbl from constant list
            payload["tables"][tbl] = rows
        except Exception:
            payload["tables"][tbl] = []
    conn.close()
    # Content-Disposition so browser downloads as file when fetched via link
    fname = f"pisowifi-backup-{payload['meta']['created_at'][:10]}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class RestoreIn(BaseModel):
    meta: dict | None = None
    tables: dict


@app.post("/api/admin/restore")
def admin_restore(body: RestoreIn, username: str = Depends(require_admin)):
    tables = body.tables
    if not isinstance(tables, dict) or not tables:
        raise HTTPException(400, "Invalid backup: missing tables")
    # Validate at least one admin user present
    if "admin_users" not in tables or not tables["admin_users"]:
        raise HTTPException(400, "Invalid backup: admin_users missing or empty (would lock out)")
    unknown = set(tables.keys()) - set(BACKUP_TABLES)
    if unknown:
        raise HTTPException(400, f"Unknown tables in backup: {', '.join(sorted(unknown))}")
    # Basic size guard
    total_rows = sum(len(v) for v in tables.values() if isinstance(v, list))
    if total_rows > 100000:
        raise HTTPException(400, "Backup too large")
    conn = db.connect()
    try:
        with db.write_tx(conn):
            conn.execute("PRAGMA foreign_keys=OFF")
            for tbl in BACKUP_TABLES:
                conn.execute(f"DELETE FROM {tbl}")  # noqa: S608 safe — tbl from constant list
            for tbl in BACKUP_TABLES:
                rows = tables.get(tbl)
                if not rows:
                    continue
                if not isinstance(rows, list):
                    raise HTTPException(400, f"Invalid data for table {tbl}")
                for row in rows:
                    if not isinstance(row, dict) or not row:
                        raise HTTPException(400, f"Invalid row in {tbl}")
                    cols = list(row.keys())
                    # Guard against injection via column names — only alphanum/_ allowed
                    for c in cols:
                        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", c):
                            raise HTTPException(400, f"Invalid column name: {c}")
                    placeholders = ",".join("?" for _ in cols)
                    col_list = ",".join(cols)
                    try:
                        conn.execute(
                            f"INSERT INTO {tbl} ({col_list}) VALUES ({placeholders})",  # noqa: S608 safe — validated names
                            [row[c] for c in cols],
                        )
                    except Exception as e:
                        raise HTTPException(400, f"Restore failed on {tbl}: {e}")
            conn.execute("PRAGMA foreign_keys=ON")
            # Re-check FK integrity
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise HTTPException(400, f"Restore failed: foreign key violations {fk_violations}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Restore failed: {e}")
    finally:
        conn.close()
    return {"ok": True, "restored_tables": list(tables.keys()), "rows": total_rows}


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
        # Only credit when a device has an active Insert Coin claim.
        if mac is None:
            # still record as ignored for audit, but don't credit balance
            conn.execute(
                "INSERT INTO coin_events(mac,delta,created_at) VALUES (?,?,?)",
                (None, body.value, db.now_iso()),
            )
            ignored = True
        else:
            conn.execute(
                "INSERT INTO coin_events(mac,delta,created_at) VALUES (?,?,?)",
                (mac, body.value, db.now_iso()),
            )
            conn.execute(
                "INSERT INTO coin_balances(mac,coins) VALUES (?,?) "
                "ON CONFLICT(mac) DO UPDATE SET coins=coins+excluded.coins",
                (mac, body.value),
            )
            # Reset/extend the active insert window on every accepted coin
            extend_coin_claim(conn, mac)
            ignored = False
    conn.close()
    if ignored:
        return {"credited": None, "coins": body.value, "ignored": True}
    return {"credited": mac, "coins": body.value}
