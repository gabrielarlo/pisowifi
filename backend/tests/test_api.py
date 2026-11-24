import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

TEST_MAC = "aa:bb:cc:dd:ee:01"
OTHER_MAC = "aa:bb:cc:dd:ee:02"


@pytest.fixture
def client():
    tmp = tempfile.mkdtemp()
    os.environ["PISO_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["PISO_MOCK_MAC"] = TEST_MAC
    os.environ["PISO_JWT_SECRET"] = "test-secret"
    os.environ["PISO_ADMIN_PASS"] = "admin@123"
    from importlib import reload
    from app import config, db, main
    reload(config)
    reload(db)
    reload(main)
    with TestClient(main.app) as c:
        yield c


def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin@123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def test_default_login_and_401(client):
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert token(client)


def test_coin_pulse_credits_claiming_mac_only(client):
    client.get("/api/portal/status")  # claim
    r = client.post("/api/internal/coin-pulse", json={"value": 2})
    assert r.status_code == 200 and r.json()["credited"] == TEST_MAC
    assert client.get("/api/portal/coins").json()["coins"] == 2
    assert client.get("/api/portal/coins", headers={"X-Dev-Mac": OTHER_MAC}).json()["coins"] == 0


def test_pulse_without_claim_credits_nobody(client):
    r = client.post("/api/internal/coin-pulse", json={"value": 1})
    assert r.json()["credited"] is None
    assert client.get("/api/portal/coins").json()["coins"] == 0


def test_purchase_spends_coins_and_creates_session(client):
    client.get("/api/portal/status")
    client.post("/api/internal/coin-pulse", json={"value": 3})
    plans = client.get("/api/portal/config").json()["plans"]
    plan = plans[0]
    r = client.post("/api/portal/purchase", json={"plan_id": plan["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["active"] is True
    assert client.get("/api/portal/coins").json()["coins"] == 3 - plan["coins_required"]
    # second purchase while active -> 409, no double-spend
    r2 = client.post("/api/portal/purchase", json={"plan_id": plan["id"]})
    assert r2.status_code == 409


def test_purchase_insufficient_coins_402(client):
    client.get("/api/portal/status")
    plans = client.get("/api/portal/config").json()["plans"]
    r = client.post("/api/portal/purchase", json={"plan_id": plans[-1]["id"]})
    assert r.status_code == 402


def test_voucher_redeem_valid_invalid_and_reuse(client):
    t = token(client)
    codes = client.post(
        "/api/admin/vouchers/generate",
        headers=auth(t),
        json={"count": 1, "duration_minutes": 45, "price": 10},
    ).json()["codes"]
    code = codes[0]
    r = client.post("/api/portal/redeem", json={"code": code})
    assert r.status_code == 200 and r.json()["session"]["active"]
    assert client.post("/api/portal/redeem", json={"code": code}).status_code == 400
    assert client.post("/api/portal/redeem", json={"code": "NOPE1234"}).status_code == 400


def test_logout_ends_session_and_all_macs(client):
    t = token(client)
    codes = client.post(
        "/api/admin/vouchers/generate",
        headers=auth(t),
        json={"count": 1, "duration_minutes": 30, "price": 10},
    ).json()["codes"]
    client.post("/api/portal/redeem", json={"code": codes[0]})
    assert TEST_MAC in client.get("/api/internal/allowed-macs").json()["macs"]
    assert client.post("/api/portal/logout").status_code == 200
    assert TEST_MAC not in client.get("/api/internal/allowed-macs").json()["macs"]


def test_client_cannot_spend_another_macs_coins(client):
    client.get("/api/portal/status")
    client.post("/api/internal/coin-pulse", json={"value": 5})
    plans = client.get("/api/portal/config").json()["plans"]
    # request carries a forged mac query param; backend must ignore it
    r = client.post(
        f"/api/portal/purchase?mac={OTHER_MAC}",
        json={"plan_id": plans[0]["id"]},
    )
    assert r.status_code == 200
    assert client.get("/api/portal/coins").json()["coins"] == 5 - plans[0]["coins_required"]
    assert client.get("/api/portal/coins", headers={"X-Dev-Mac": OTHER_MAC}).json()["coins"] == 0


def test_admin_crud_and_password_change(client):
    t = token(client)
    assert client.get("/api/admin/hardware", headers=auth(t)).json()["coin_pulse_pin"] == 3
    assert client.put(
        "/api/admin/hardware",
        headers=auth(t),
        json={"coin_pulse_pin": 11, "relay_pin": 5, "gpio_enabled": False, "relay_active": False},
    ).status_code == 200
    assert client.put(
        "/api/admin/hardware",
        headers=auth(t),
        json={"coin_pulse_pin": 99, "relay_pin": 5, "gpio_enabled": False, "relay_active": False},
    ).status_code == 400
    assert client.put(
        "/api/admin/settings", headers=auth(t), json={"hotspot_name": "Test Hotspot"}
    ).status_code == 200
    assert client.get("/api/portal/config").json()["hotspot_name"] == "Test Hotspot"
    assert client.post(
        "/api/auth/change-password",
        headers=auth(t),
        json={"old_password": "admin@123", "new_password": "newpass123"},
    ).status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin@123"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "newpass123"}
    ).status_code == 200


def test_dev_mac_header_validated_and_ignored_without_mock(client, monkeypatch):
    assert client.get("/api/portal/coins", headers={"X-Dev-Mac": "not-a-mac"}).status_code == 400

    from app import config, main

    monkeypatch.setattr(config, "MOCK_MAC", "")
    monkeypatch.setattr(main, "neighbor_mac", lambda ip, conn=None: None)
    request = SimpleNamespace(headers={"x-dev-mac": OTHER_MAC}, client=SimpleNamespace(host="127.0.0.1"))
    with pytest.raises(HTTPException) as exc:
        main.client_mac(request)
    assert exc.value.status_code == 400


def test_resolve_mac_rejects_invalid_ip(client):
    assert client.get("/api/internal/resolve-mac", params={"ip": "not-an-ip"}).status_code == 400


def test_voucher_conflict_does_not_consume_voucher(client):
    t = token(client)
    codes = client.post(
        "/api/admin/vouchers/generate",
        headers=auth(t),
        json={"count": 2, "duration_minutes": 45, "price": 10},
    ).json()["codes"]
    assert client.post("/api/portal/redeem", json={"code": codes[0]}).status_code == 200
    assert client.post("/api/portal/redeem", json={"code": codes[1]}).status_code == 409
    conn = sqlite3.connect(os.environ["PISO_DB_PATH"])
    assert conn.execute("SELECT status FROM vouchers WHERE code=?", (codes[1],)).fetchone()[0] == "unused"
    conn.close()


def test_compose_keeps_backend_private():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    dockerfile = (root / "backend" / "Dockerfile").read_text()
    assert "8000:8000" not in compose
    assert "PISO_MOCK_MAC" not in dockerfile
    assert "dev-only-change-me" not in compose + dockerfile
