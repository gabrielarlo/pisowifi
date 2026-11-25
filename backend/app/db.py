import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ADMIN_PASS, ADMIN_USER, DB_PATH
from .auth import hash_password


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def expiry_iso(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # shortcut: NORMAL + MEMORY + autocheckpoint reduces SD wear, but a power cut
    # may lose the last committed transaction; mitigated by pisowifi-sync checkpoint every 30s
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def write_tx(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 duration_minutes INTEGER NOT NULL,
 coins_required INTEGER NOT NULL DEFAULT 1,
 price REAL NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 qos_down_mbps INTEGER,
 qos_up_mbps INTEGER
);
CREATE TABLE IF NOT EXISTS vouchers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT UNIQUE NOT NULL,
 duration_minutes INTEGER NOT NULL,
 price REAL NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'unused',
 created_at TEXT NOT NULL,
 used_at TEXT,
 used_by_mac TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 mac TEXT NOT NULL,
 ip TEXT,
 plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
 started_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 ended_at TEXT,
 source TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1,
 paused INTEGER NOT NULL DEFAULT 0,
 paused_at TEXT,
 paused_remaining INTEGER,
 last_seen TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 mac TEXT NOT NULL,
 plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
 amount REAL NOT NULL,
 method TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coin_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 mac TEXT,
 delta INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coin_balances (
 mac TEXT PRIMARY KEY,
 coins INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coin_claims (
 mac TEXT PRIMARY KEY,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
  mac TEXT PRIMARY KEY,
  ip TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  hits INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bandwidth_samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 mac TEXT,
 ip TEXT,
 rx_bytes INTEGER NOT NULL DEFAULT 0,
 tx_bytes INTEGER NOT NULL DEFAULT 0,
 recorded_at TEXT NOT NULL
);
"""

DEFAULTS = {
    "hotspot_name": "Piso WiFi",
    "terms": "Pay as you go internet. Insert a coin or enter a voucher code to start.",
    "currency": "PHP",
    "coin_value": "1,5,10,20",
    "coin_pulse_pin": "3",
    "relay_pin": "11",
    "gpio_enabled": "0",
    "relay_active": "0",
    "ap_mac": "",
    "coin_countdown": "60",
    "banner_subtitle": "Pay as you go internet",
    "banner_bg": "#1d4ed8",
    "banner_fg": "#ffffff",
    "qos_enabled": "1",
    "qos_per_guest_down_mbps": "10",
    "qos_per_guest_up_mbps": "10",
    "qos_global_down_mbps": "320",
    "qos_global_up_mbps": "320",
    "session_pause_enabled": "1",
}


def _migrate_sessions_pause_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "paused" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
    if "paused_at" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN paused_at TEXT")
    if "paused_remaining" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN paused_remaining INTEGER")
    if "last_seen" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_seen TEXT")


def _migrate_plans_qos_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(plans)").fetchall()}
    if "qos_down_mbps" not in cols:
        conn.execute("ALTER TABLE plans ADD COLUMN qos_down_mbps INTEGER")
    if "qos_up_mbps" not in cols:
        conn.execute("ALTER TABLE plans ADD COLUMN qos_up_mbps INTEGER")


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate_sessions_pause_columns(conn)
    _migrate_plans_qos_columns(conn)
    with write_tx(conn):
        for key, value in DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))
        # Migrate single coin_value to multi-denomination default
        row = conn.execute("SELECT value FROM settings WHERE key='coin_value'").fetchone()
        if row and row[0].strip() == "1":
            conn.execute("UPDATE settings SET value=? WHERE key='coin_value'", ("1,5,10,20",))
        row = conn.execute("SELECT value FROM settings WHERE key='coin_countdown'").fetchone()
        if row and row[0] == "15":
            conn.execute("UPDATE settings SET value=? WHERE key='coin_countdown'", ("10",))
        # Insert-only: never clobber a password the admin has changed.
        if conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone() is None:
            conn.execute(
                "INSERT INTO admin_users(username,password_hash,created_at) VALUES (?,?,?)",
                (ADMIN_USER, hash_password(ADMIN_PASS), now_iso()),
            )
        if conn.execute("SELECT 1 FROM plans LIMIT 1").fetchone() is None:
            conn.executemany(
                "INSERT INTO plans(name,duration_minutes,coins_required,price,active) VALUES (?,?,?,?,1)",
                [
                    ("3 hours", 180, 5, 5.0),
                    ("7 hours", 420, 10, 10.0),
                    ("16 hours", 960, 20, 20.0),
                ],
            )
    conn.close()


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def active_session(conn, mac):
    row = conn.execute(
        "SELECT * FROM sessions WHERE mac=? AND active=1 ORDER BY id DESC LIMIT 1",
        (mac,),
    ).fetchone()
    if not row:
        return None
    # Paused sessions are still considered active (they have remaining time frozen).
    if row["paused"]:
        return row
    # Unpaused must not be expired
    if row["expires_at"] <= now_iso():
        return None
    return row


def allowed_macs(conn):
    return [
        r["mac"]
        for r in conn.execute(
            "SELECT DISTINCT mac FROM sessions WHERE active=1 AND paused=0 AND expires_at>?", (now_iso(),)
        )
    ]


def pause_session(conn, session_row):
    if not session_row or session_row["paused"]:
        return session_row
    try:
        from datetime import datetime, timezone
        expires = datetime.fromisoformat(session_row["expires_at"])
        now = datetime.now(timezone.utc)
        remaining = max(0, int((expires - now).total_seconds()))
    except Exception:
        remaining = 0
    if remaining <= 0:
        # Already expired — deactivate instead of pausing
        conn.execute(
            "UPDATE sessions SET active=0, ended_at=?, paused=0 WHERE id=?",
            (now_iso(), session_row["id"]),
        )
        return None
    conn.execute(
        "UPDATE sessions SET paused=1, paused_at=?, paused_remaining=?, last_seen=? WHERE id=?",
        (now_iso(), remaining, now_iso(), session_row["id"]),
    )
    return conn.execute("SELECT * FROM sessions WHERE id=?", (session_row["id"],)).fetchone()


def resume_session(conn, session_row):
    if not session_row or not session_row["paused"]:
        return session_row
    remaining = session_row["paused_remaining"]
    if remaining is None or int(remaining) <= 0:
        conn.execute(
            "UPDATE sessions SET active=0, ended_at=?, paused=0, paused_remaining=NULL, paused_at=NULL WHERE id=?",
            (now_iso(), session_row["id"]),
        )
        return None
    try:
        from datetime import datetime, timedelta, timezone
        new_expires = (datetime.now(timezone.utc) + timedelta(seconds=int(remaining))).isoformat()
    except Exception:
        from datetime import timedelta as _td, datetime as _dt, timezone as _tz
        new_expires = (_dt.now(_tz.utc) + _td(seconds=int(remaining))).isoformat()
    conn.execute(
        "UPDATE sessions SET paused=0, paused_at=NULL, paused_remaining=NULL, expires_at=?, last_seen=? WHERE id=?",
        (new_expires, now_iso(), session_row["id"]),
    )
    return conn.execute("SELECT * FROM sessions WHERE id=?", (session_row["id"],)).fetchone()


def pause_all_active_sessions(conn):
    """Pause all unpaused active sessions — used on OPI boot (power interruption)."""
    rows = conn.execute(
        "SELECT * FROM sessions WHERE active=1 AND paused=0 AND expires_at>?", (now_iso(),)
    ).fetchall()
    for r in rows:
        pause_session(conn, r)


def heartbeat_and_maybe_resume(conn, mac):
    row = conn.execute(
        "SELECT * FROM sessions WHERE mac=? AND active=1 ORDER BY id DESC LIMIT 1", (mac,)
    ).fetchone()
    if not row:
        return None
    # If expired and not paused, deactivate
    if not row["paused"] and row["expires_at"] <= now_iso():
        conn.execute("UPDATE sessions SET active=0, ended_at=? WHERE id=?", (now_iso(), row["id"]))
        return None
    if row["paused"]:
        row = resume_session(conn, row)
        if not row:
            return None
        return row
    # Heartbeat: update last_seen while connected
    conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now_iso(), row["id"]))
    return row


def track_device(conn, mac, ip=None):
    # Record every portal guest (even idle, no voucher/coin) — one row per MAC.
    now = now_iso()
    conn.execute(
        "INSERT INTO devices(mac,ip,first_seen,last_seen,hits) VALUES (?,?,?,?,1) "
        "ON CONFLICT(mac) DO UPDATE SET last_seen=excluded.last_seen, "
        "ip=COALESCE(excluded.ip, devices.ip), hits=devices.hits+1",
        (mac, ip, now, now),
    )
