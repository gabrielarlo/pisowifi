#!/usr/bin/env python3
"""Coin-slot daemon: watches a GPIO pulse pin, credits the claiming client via
the local API, and holds the relay/inhibit line for its lifetime.
"""
import sqlite3
import subprocess
import sys
import time
import urllib.request

DB = "/var/lib/pisowifi/pisowifi.db"
API = "http://127.0.0.1:8000/api/internal/coin-pulse"
PIN_MAP = {3: ("gpiochip0", 12), 5: ("gpiochip0", 11), 11: ("gpiochip0", 1)}
DEBOUNCE = 0.2


def config():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = dict(conn.execute("SELECT key,value FROM settings"))
    conn.close()
    return {
        "enabled": rows.get("gpio_enabled") == "1",
        "pulse_pin": int(rows.get("coin_pulse_pin", 3)),
        "relay_pin": int(rows.get("relay_pin", 11)),
        "relay_active": rows.get("relay_active") == "1",
    }


def credit():
    req = urllib.request.Request(
        API, data=b'{"value":1}', headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status
    except Exception as exc:  # never credit on a failed API call
        print(f"coin-pulse failed: {exc}", file=sys.stderr, flush=True)
        return None


def start_relay(pin, active):
    if pin not in PIN_MAP:
        return None
    chip, offset = PIN_MAP[pin]
    try:
        return subprocess.Popen(
            ["gpioset", "--mode=wait", chip, f"{offset}={1 if active else 0}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("gpioset missing", file=sys.stderr, flush=True)
        return None


def main():
    cfg = config()
    if not cfg["enabled"]:
        print("GPIO disabled; coind idle", flush=True)
        while True:
            time.sleep(30)
            if config()["enabled"]:
                print("GPIO enabled; restart coind", flush=True)
                return
    if cfg["pulse_pin"] not in PIN_MAP:
        print(f"unsupported coin pulse pin {cfg['pulse_pin']}", file=sys.stderr, flush=True)
        return

    chip, offset = PIN_MAP[cfg["pulse_pin"]]
    relay = start_relay(cfg["relay_pin"], cfg["relay_active"])
    relay_key = (cfg["relay_pin"], cfg["relay_active"])
    proc = subprocess.Popen(
        ["gpiomon", chip, str(offset)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    last = 0.0
    while proc.poll() is None:
        line = proc.stdout.readline()
        if not line:
            break
        if "falling" not in line.lower():
            continue
        now = time.monotonic()
        if now - last < DEBOUNCE:
            continue  # mechanical chatter: one coin, one credit
        last = now
        credit()
        current = config()
        key = (current["relay_pin"], current["relay_active"])
        if key != relay_key:
            if relay:
                relay.terminate()
            relay = start_relay(*key)
            relay_key = key
    if relay:
        relay.terminate()


if __name__ == "__main__":
    main()
