"""Session run (paper/shadow) + manual confirmation flow via REST."""
from __future__ import annotations

ADMIN = {"email": "admin@example.com", "password": "test-password-123"}


async def _login(client):
    r = await client.post("/api/v1/auth/login", json=ADMIN)
    assert r.status_code == 200
    return client.cookies.get("cqb_csrf")


async def test_run_paper_session_summary_and_journal(client):
    csrf = await _login(client)
    r = await client.post("/api/v1/sessions/run",
                          headers={"x-csrf-token": csrf},
                          json={"asset": "BTCUSDT", "mode": "PAPER", "n_candles": 300, "seed": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "PAPER"
    assert body["journal_ok"] is True
    assert abs(body["break_even"] - (1 / 1.8)) < 1e-6
    assert body["final_balance"] is not None


async def test_shadow_session_has_no_balance(client):
    csrf = await _login(client)
    r = await client.post("/api/v1/sessions/run", headers={"x-csrf-token": csrf},
                          json={"asset": "BTCUSDT", "mode": "SHADOW", "n_candles": 250})
    assert r.status_code == 200
    assert r.json()["final_balance"] is None


async def test_manual_mode_rejected_by_run(client):
    csrf = await _login(client)
    r = await client.post("/api/v1/sessions/run", headers={"x-csrf-token": csrf},
                          json={"asset": "BTCUSDT", "mode": "MANUAL"})
    assert r.status_code == 400


async def test_manual_confirm_and_result_compares_theoretical(client):
    csrf = await _login(client)
    h = {"x-csrf-token": csrf}
    # confirm a CALL entered at 1.10
    r = await client.post("/api/v1/manual/confirm", headers=h, json={
        "asset": "EURUSD_OTC", "action": "CALL", "p_up": 0.62,
        "entry_price": 1.10, "payout": 0.8, "external_id": "abc123"})
    assert r.status_code == 200, r.text
    trade_id = r.json()["trade_id"]

    # report a WON with exit above entry -> theoretical WON, agrees
    r2 = await client.post(f"/api/v1/manual/{trade_id}/result", headers=h,
                           json={"result": "WON", "exit_price": 1.101})
    assert r2.status_code == 200
    body = r2.json()
    assert body["theoretical_result"] == "WON"
    assert body["external_matches_theoretical"] is True


async def test_manual_disagreement_flagged(client):
    csrf = await _login(client)
    h = {"x-csrf-token": csrf}
    r = await client.post("/api/v1/manual/confirm", headers=h, json={
        "asset": "EURUSD_OTC", "action": "CALL", "p_up": 0.6, "entry_price": 1.10})
    trade_id = r.json()["trade_id"]
    # broker says WON but price fell -> theoretical LOST, disagreement flagged
    r2 = await client.post(f"/api/v1/manual/{trade_id}/result", headers=h,
                           json={"result": "WON", "exit_price": 1.099})
    body = r2.json()
    assert body["theoretical_result"] == "LOST"
    assert body["external_matches_theoretical"] is False


async def test_manual_confirm_requires_csrf(client):
    await _login(client)
    r = await client.post("/api/v1/manual/confirm", json={
        "asset": "EURUSD_OTC", "action": "CALL", "entry_price": 1.10})
    assert r.status_code == 403
