"""Market REST + WebSocket integration (synthetic feed, fast pacing)."""
from __future__ import annotations

import os

os.environ["FEED_SPEED_SECONDS"] = "0.01"  # fast ticks for tests

import pytest
from starlette.testclient import TestClient

ADMIN = {"email": "admin@example.com", "password": "test-password-123"}


@pytest.fixture
def sync_client():
    # Starlette's TestClient drives the app (incl. async lifespan) on its own
    # event loop and supports websockets. Lifespan shutdown stops market feeds.
    from cryptoption_api.main import create_app
    from cryptoption_api.settings import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client


def _login(client: TestClient) -> None:
    r = client.post("/api/v1/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text


def test_assets_seeded_and_listed(sync_client):
    _login(sync_client)
    r = sync_client.get("/api/v1/market/assets")
    assert r.status_code == 200
    symbols = {a["symbol"] for a in r.json()}
    assert {"BTCUSDT", "EURUSD_OTC"} <= symbols
    # OTC vs crypto stay distinguished
    otc = next(a for a in r.json() if a["symbol"] == "EURUSD_OTC")
    assert otc["is_otc"] is True and otc["market_type"] == "FOREX_OTC"


def test_ws_requires_auth(sync_client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with sync_client.websocket_connect("/ws?asset=BTCUSDT") as ws:
            ws.receive_text()


def test_ws_streams_sequenced_ticks(sync_client):
    _login(sync_client)
    with sync_client.websocket_connect("/ws?asset=BTCUSDT") as ws:
        first = ws.receive_json()
        assert first["type"] == "connection.status"
        assert first["seq"] == 0
        # collect a few market messages and assert monotonic sequence + a tick
        seqs = [first["seq"]]
        saw_tick = False
        for _ in range(6):
            msg = ws.receive_json()
            seqs.append(msg["seq"])
            if msg["type"] == "market.tick":
                saw_tick = True
                assert "price" in msg["payload"]
        assert saw_tick
        assert seqs == sorted(seqs)  # monotonic, gap-detectable
        assert len(set(seqs)) == len(seqs)  # no duplicates


def test_data_quality_endpoint_flags_gap(sync_client):
    _login(sync_client)
    base = "2024-01-01T00:0{}:00+00:00"
    candles = [
        {"ts_utc": base.format(i), "asset": "X", "open": 1.0, "high": 1.1,
         "low": 0.9, "close": 1.0, "volume": 1.0}
        for i in range(0, 4)
    ]
    # jump 30 minutes -> gap
    candles.append({"ts_utc": "2024-01-01T00:34:00+00:00", "asset": "X", "open": 1.0,
                    "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0})
    r = sync_client.post("/api/v1/data-quality/validate",
                         json={"bar_seconds": 60, "candles": candles})
    assert r.status_code == 200
    codes = {i["code"] for i in r.json()["issues"]}
    assert "GAP" in codes
