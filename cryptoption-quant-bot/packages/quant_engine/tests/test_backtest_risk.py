"""Phase 4: backtest PnL/payout, risk invariants (anti-martingale), metrics, MC."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_engine.backtest import (
    BinaryBacktestEngine,
    break_even_win_rate,
    compute_metrics,
    decision_threshold,
    ruin_probability,
)
from quant_engine.config import BacktestConfig, RiskConfig
from quant_engine.paper import PaperBroker
from quant_engine.risk import RiskManager


def _samples(n=200, seed=3):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    y = rng.integers(0, 2, n)
    return pd.DataFrame({
        "ts_utc": ts, "asset": "X_OTC", "session_id": ts.strftime("%Y-%m-%d"),
        "signal_idx": np.arange(n), "entry_idx": np.arange(n) + 1,
        "horizon_end": np.arange(n) + 1, "entry_price": 1.0,
        "expiry_price": np.where(y == 1, 1.001, 0.999), "y_up": y, "is_tie": False,
    })


# ---- break-even + PnL math ----

def test_break_even_formula():
    assert break_even_win_rate(0.80) == pytest.approx(0.5556, abs=1e-4)


def test_win_pays_stake_times_payout():
    cfg = BacktestConfig(payout_base=0.8, payout_jitter=0.0, payout_floor=0.7, rejection_prob=0.0)
    s = _samples()
    p_up = np.where(s["y_up"] == 1, 0.99, 0.01)  # oracle
    res = BinaryBacktestEngine(cfg, RiskConfig(risk_per_trade=0.005)).run(s, p_up, 0.6)
    settled = res.trade_log[res.trade_log["outcome"].isin(["win", "loss"])]
    assert (settled["outcome"] == "win").all()
    first = settled.iloc[0]
    assert first["pnl"] == pytest.approx(first["stake"] * 0.8)


def test_inverted_oracle_loses():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    s = _samples()
    oracle = np.where(s["y_up"] == 1, 0.99, 0.01)
    good = BinaryBacktestEngine(cfg, RiskConfig()).run(s, oracle, 0.6)
    bad = BinaryBacktestEngine(cfg, RiskConfig()).run(s, 1 - oracle, 0.6)
    assert good.trade_log["pnl"].sum() > 0 > bad.trade_log["pnl"].sum()


def test_variable_payout_within_bounds():
    cfg = BacktestConfig(payout_base=0.8, payout_jitter=0.05, payout_floor=0.7, rejection_prob=0.0)
    s = _samples()
    res = BinaryBacktestEngine(cfg, RiskConfig()).run(s, np.full(len(s), 0.99), 0.6)
    payouts = res.trade_log.loc[res.trade_log["payout"] > 0, "payout"]
    assert (payouts >= 0.7).all() and (payouts <= 0.85 + 1e-9).all()
    assert payouts.nunique() > 1  # actually varies


def test_one_open_trade_per_asset():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    s = _samples()
    s["horizon_end"] = s["signal_idx"] + 5  # long expiry -> overlaps
    res = BinaryBacktestEngine(cfg, RiskConfig(max_trades_per_session=10_000)).run(
        s, np.full(len(s), 0.99), 0.6)
    settled = res.trade_log[res.trade_log["outcome"].isin(["win", "loss", "tie"])]
    idx = settled["ts_utc"].map(lambda t: s.index[s["ts_utc"] == t][0]).to_numpy()
    assert (np.diff(np.sort(idx)) >= 6).all()


def test_threshold_uses_floor_payout_and_margin():
    cfg = BacktestConfig(payout_floor=0.7, threshold_margin=0.02, threshold_use_val_ci=False)
    assert decision_threshold(cfg) == pytest.approx(1 / 1.7 + 0.02)


def test_no_trade_below_threshold():
    cfg = BacktestConfig()
    res = BinaryBacktestEngine(cfg, RiskConfig()).run(_samples(), np.full(200, 0.5),
                                                      decision_threshold(cfg))
    assert res.trade_log.empty


def test_events_collected():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    s = _samples(30)
    res = BinaryBacktestEngine(cfg, RiskConfig()).run(
        s, np.full(len(s), 0.99), 0.6, collect_events=True)
    kinds = {type(e).__name__ for e in res.events}
    assert "PredictionEvent" in kinds and "SettlementEvent" in kinds


# ---- risk invariants ----

def test_default_stake_is_quarter_percent():
    m = RiskManager(RiskConfig(initial_capital=10_000))
    d = m.pre_trade("2024-01-01", 0)
    assert d.allowed and d.stake == pytest.approx(25.0)


def test_risk_fraction_hard_cap_rejected():
    with pytest.raises(ValueError):
        RiskConfig(risk_per_trade=0.01)


def test_anti_martingale_stake_never_grows_after_loss():
    m = RiskManager(RiskConfig(initial_capital=10_000, max_consecutive_losses=10**9,
                               daily_loss_limit=0.99, max_trades_per_session=10**9))
    prev = None
    for bar in range(300):
        d = m.pre_trade("2024-01-01", bar)
        if not d.allowed:
            break
        if prev is not None:
            assert d.stake <= prev + 1e-9, "stake grew after a loss (martingale!)"
        prev = d.stake
        m.settle(d.stake, -d.stake)


def test_three_consecutive_losses_cooldown():
    m = RiskManager(RiskConfig(max_consecutive_losses=3, cooldown_bars=60))
    for bar in range(3):
        d = m.pre_trade("2024-01-01", bar)
        m.settle(d.stake, -d.stake)
    d = m.pre_trade("2024-01-01", 3)
    assert not d.allowed and d.reason == "MAX_CONSECUTIVE_LOSSES"
    assert not m.pre_trade("2024-01-01", 10).allowed  # cooling off
    assert m.pre_trade("2024-01-01", 3 + 61).allowed


def test_daily_loss_limit_and_kill_switch():
    m = RiskManager(RiskConfig(initial_capital=10_000, daily_loss_limit=0.01,
                               max_consecutive_losses=10**9, max_trades_per_session=10**9))
    bar = 0
    while True:
        d = m.pre_trade("2024-01-01", bar)
        if not d.allowed:
            break
        m.settle(d.stake, -d.stake)
        bar += 1
    assert d.reason == "DAILY_LOSS_LIMIT"
    m2 = RiskManager(RiskConfig())
    m2.kill()
    assert m2.pre_trade("2024-01-01", 0).reason == "KILL_SWITCH"


def test_drawdown_reduces_exposure():
    m = RiskManager(RiskConfig(initial_capital=10_000, drawdown_soft_limit=0.05,
                               drawdown_scale=0.5, max_consecutive_losses=10**9,
                               daily_loss_limit=0.99, max_trades_per_session=10**9))
    d0 = m.pre_trade("2024-01-01", 0)
    m.settle(d0.stake, -600.0)  # 6% drawdown
    d1 = m.pre_trade("2024-01-01", 1)
    assert d1.stake == pytest.approx(round(m.capital * 0.0025 * 0.5, 2))


# ---- metrics + MC + paper broker ----

def test_metrics_and_ruin():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    s = _samples(400)
    p_up = np.random.default_rng(0).uniform(0, 1, len(s))
    res = BinaryBacktestEngine(cfg, RiskConfig()).run(s, p_up, 0.6)
    m = compute_metrics(res.trade_log, 10_000, n_signals=len(s), p_up_all=p_up,
                        y_up_all=s["y_up"].to_numpy(), n_bootstrap=200)
    if m.n_trades:
        assert m.win_rate_ci_lo <= m.win_rate <= m.win_rate_ci_hi
        assert np.isfinite(m.brier) and np.isfinite(m.ece)
        r = ruin_probability(res.trade_log, 10_000, 0.0025, n_paths=200, horizon_trades=200)
        assert 0 <= r.prob_ruin <= 1


def test_paper_broker_ledger():
    b = PaperBroker(balance=100.0)
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    assert not b.place(ts, "X", "CALL", 200.0, 0.8).accepted  # over balance
    assert b.place(ts, "X", "CALL", 10.0, 0.8).accepted
    s = b.settle(ts, "X", "win", 10.0, 0.8)
    assert s.pnl == pytest.approx(8.0)
    assert b.balance == pytest.approx(108.0)
    assert len(b.settlements) == 1
