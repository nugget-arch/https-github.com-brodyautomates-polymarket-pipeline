"""Health/readiness and the execution-disabled safety invariant."""

from __future__ import annotations


async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Safety invariant surfaced to clients: real execution is OFF.
    assert body["execution_enabled"] is False


async def test_ready_reports_db(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
