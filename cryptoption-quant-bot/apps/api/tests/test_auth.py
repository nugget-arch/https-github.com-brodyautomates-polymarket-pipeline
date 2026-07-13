"""Auth flow, role/session protection, CSRF, and the broker safety placeholder."""

from __future__ import annotations

import pytest

ADMIN = {"email": "admin@example.com", "password": "test-password-123"}


async def test_login_sets_cookies_and_me(client):
    r = await client.post("/api/v1/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "ADMIN"
    assert "cqb_session" in r.cookies
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN["email"]


async def test_login_bad_password_401(client):
    r = await client.post("/api/v1/auth/login", json={**ADMIN, "password": "wrong"})
    assert r.status_code == 401


async def test_dashboard_requires_auth(client):
    r = await client.get("/api/v1/dashboard/state")
    assert r.status_code == 401


async def test_dashboard_after_login(client):
    await client.post("/api/v1/auth/login", json=ADMIN)
    r = await client.get("/api/v1/dashboard/state")
    assert r.status_code == 200
    body = r.json()
    # break-even for payout 0.80 must be ~0.5556 and drive the thresholds
    assert abs(body["break_even"] - (1 / 1.8)) < 1e-6
    assert body["current_action"] == "NO_TRADE"
    assert body["kill_switch"] is False


async def test_logout_requires_csrf(client):
    await client.post("/api/v1/auth/login", json=ADMIN)
    # no CSRF header -> rejected
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 403
    # with matching CSRF header from cookie -> ok
    csrf = client.cookies.get("cqb_csrf")
    r2 = await client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    assert r2.status_code == 200


def test_official_adapter_is_disabled_placeholder():
    from quant_engine.execution import (
        OfficialApiUnavailableError,
        OfficialCryptOptionBrokerAdapter,
        OrderRequest,
    )

    adapter = OfficialCryptOptionBrokerAdapter()
    with pytest.raises(OfficialApiUnavailableError):
        adapter.get_balance()
    with pytest.raises(OfficialApiUnavailableError):
        adapter.place_order(OrderRequest("BTCUSDT", "CALL", 1.0, 60))


def test_execution_globally_disabled():
    import quant_engine

    assert quant_engine.EXECUTION_ENABLED is False
