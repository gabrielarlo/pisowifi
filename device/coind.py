#!/usr/bin/env python3
"""Coin-slot daemon: watches a GPIO pulse pin, credits the claiming client via
the local API, and holds the relay/inhibit line for its lifetime.

Supports multi-denomination coins (e.g. 1,5,10,20 PHP) where the validator
emits N rapid pulses for an N-PHP coin. Pulses within a short window are
counted as one coin and credited as N coins (so a 5 PHP coin = 5 pulses = 5 coins).
Single-pulse validators still work: 1 pulse = 1 coin.
"""
import select
import sqlite3
import subprocess
import sys
import time
import urllib.request

DB = "/var/lib/pisowifi/pisowifi.db"
API = "http://127.0.0.1:8000/api/internal/coin-pulse"
PIN_MAP = {3: ("gpiochip0", 12), 5: ("gpiochip0", 11), 11: ("gpiochip0", 1)}
DEBOUNCE = 0.04
WINDOW = 0.8  # collect pulses for one coin within this window


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


def allowed_coins():
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = conn.execute("SELECT value FROM settings WHERE key='coin_value'").fetchone()
        conn.close()
        if not row or not row[0].strip():
            return {1, 5, 10, 20}
        vals = [int(x.strip()) for x in row[0].split(",") if x.strip().isdigit()]
        return set(vals) if vals else {1, 5, 10, 20}
    except Exception:
        return {1, 5, 10, 20}


def credit(value=1):
    req = urllib.request.Request(
        API, data=f'{{"value":{int(value)}}}'.encode(), headers={"Content-Type": "application/json"}, method="POST"
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
        ["gpiomon", chip, str(offset)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    last = 0.0
    pending = 0
    last_pulse = 0.0
    while proc.poll() is None:
        # If we have pending pulses and window expired, credit them as one coin value
        if pending > 0 and time.monotonic() - last_pulse > WINDOW:
            allowed = allowed_coins()
            if pending in allowed:
                credit(pending)
            else:
                print(f"coin {pending} ignored (not in {allowed})", file=sys.stderr, flush=True)
            pending = 0
            current = config()
            key = (current["relay_pin"], current["relay_active"])
            if key != relay_key:
                if relay:
                    relay.terminate()
                relay = start_relay(*key)
                relay_key = key
            continue
        # Wait for next pulse with short timeout so we can check window expiry
        rlist, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not rlist:
            continue
        line = proc.stdout.readline()
        if not line:
            break
        if "falling" not in line.lower():
            continue
        now = time.monotonic()
        if now - last < DEBOUNCE:
            continue
        last = now
        # Count this pulse toward current coin
        if pending == 0:
            last_pulse = now
        else:
            # If too long since last pulse, previous coin already credited above; start new
            if now - last_pulse > WINDOW:
                # Should have been credited, but handle edge
                allowed = allowed_coins()
                if pending in allowed:
                    credit(pending)
                else:
                    print(f"coin {pending} ignored (not in {allowed})", file=sys.stderr, flush=True)
                pending = 0
                last_pulse = now
        pending += 1
        last_pulse = now
        # Check relay config changes without waiting for credit
        current = config()
        key = (current["relay_pin"], current["relay_active"])
        if key != relay_key:
            if relay:
                relay.terminate()
            relay = start_relay(*key)
            relay_key = key
    # Credit any remaining pending on exit
    if pending > 0:
        allowed = allowed_coins()
        if pending in allowed:
            credit(pending)
        else:
            print(f"coin {pending} ignored (not in {allowed})", file=sys.stderr, flush=True)
    if relay:
        relay.terminate()


if __name__ == "__main__":
    main()
