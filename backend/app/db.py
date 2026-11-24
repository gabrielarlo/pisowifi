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
 active INTEGER NOT NULL DEFAULT 1
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
 active INTEGER NOT NULL DEFAULT 1
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
CREATE TABLE IF NOT EXISTS settings (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
"""

DEFAULTS = {
    "hotspot_name": "Piso WiFi",
    "terms": "Pay as you go internet. Insert a coin or enter a voucher code to start.",
    "currency": "PHP",
    "coin_value": "1",
    "coin_pulse_pin": "3",
    "relay_pin": "11",
    "gpio_enabled": "0",
    "relay_active": "0",
    "ap_mac": "",
}


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    with write_tx(conn):
        for key, value in DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))
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
                    ("30 minutes", 30, 1, 10.0),
                    ("1 hour", 60, 2, 20.0),
                    ("2 hours", 120, 4, 40.0),
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
    return conn.execute(
        "SELECT * FROM sessions WHERE mac=? AND active=1 AND expires_at>? ORDER BY id DESC LIMIT 1",
        (mac, now_iso()),
    ).fetchone()


def allowed_macs(conn):
    return [
        r["mac"]
        for r in conn.execute(
            "SELECT DISTINCT mac FROM sessions WHERE active=1 AND expires_at>?", (now_iso(),)
        )
    ]
