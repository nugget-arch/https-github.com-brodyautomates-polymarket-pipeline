import numpy as np
import pandas as pd
import pytest

from otc_lab.backtest.engine import BinaryBacktestEngine, decision_threshold
from otc_lab.backtest.metrics import compute_metrics
from otc_lab.backtest.monte_carlo import ruin_probability
from otc_lab.config import BacktestConfig, RiskConfig, break_even_win_rate


def _samples(n=200, seed=3):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    y = rng.integers(0, 2, n)
    return pd.DataFrame({
        "timestamp": ts, "asset": "X_OTC", "session": ts.strftime("%Y-%m-%d"),
        "signal_idx": np.arange(n), "entry_idx": np.arange(n) + 1,
        "horizon_end": np.arange(n) + 1,
        "entry_price": 1.0, "expiry_price": np.where(y == 1, 1.001, 0.999),
        "y_up": y, "is_tie": False,
    })


def test_break_even_formula():
    assert break_even_win_rate(0.80) == pytest.approx(1 / 1.8)
    assert break_even_win_rate(0.80) == pytest.approx(0.5556, abs=1e-4)


def test_pnl_arithmetic_win_stake_times_payout():
    cfg = BacktestConfig(payout_base=0.8, payout_jitter=0.0, payout_floor=0.7,
                         rejection_prob=0.0)
    risk = RiskConfig(initial_capital=1000.0, risk_per_trade=0.005)
    s = _samples()
    p_up = np.where(s["y_up"] == 1, 0.99, 0.01)  # oracle
    log = BinaryBacktestEngine(cfg, risk).run(s, p_up, threshold=0.6)
    settled = log[log["outcome"].isin(["win", "loss"])]
    assert (settled["outcome"] == "win").all()
    first = settled.iloc[0]
    assert first["pnl"] == pytest.approx(first["stake"] * 0.8)


def test_perfect_and_inverted_oracle():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    risk = RiskConfig()
    s = _samples()
    oracle = np.where(s["y_up"] == 1, 0.99, 0.01)
    log_good = BinaryBacktestEngine(cfg, risk).run(s, oracle, 0.6)
    log_bad = BinaryBacktestEngine(cfg, risk).run(s, 1 - oracle, 0.6)
    assert log_good["pnl"].sum() > 0
    assert log_bad["pnl"].sum() < 0


def test_one_open_trade_per_asset():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    risk = RiskConfig(max_trades_per_session=10_000)
    s = _samples()
    s["horizon_end"] = s["signal_idx"] + 5  # long expiry -> overlaps
    p_up = np.full(len(s), 0.99)
    log = BinaryBacktestEngine(cfg, risk).run(s, p_up, 0.6)
    executed = log[log["outcome"].isin(["win", "loss", "tie"])]
    sig = s.set_index("timestamp").loc[executed["timestamp"]]["signal_idx"].to_numpy()
    assert (np.diff(sig) >= 6).all(), "overlapping trades on one asset"


def test_threshold_uses_floor_payout_and_margin():
    cfg = BacktestConfig(payout_base=0.8, payout_floor=0.7, threshold_margin=0.02,
                         threshold_use_val_ci=False)
    thr = decision_threshold(cfg)
    assert thr == pytest.approx(1 / 1.7 + 0.02)


def test_no_trades_below_threshold():
    cfg = BacktestConfig()
    risk = RiskConfig()
    s = _samples()
    p_up = np.full(len(s), 0.5)  # no conviction
    log = BinaryBacktestEngine(cfg, risk).run(s, p_up, decision_threshold(cfg))
    assert log.empty


def test_metrics_and_ruin_smoke():
    cfg = BacktestConfig(payout_jitter=0.0, rejection_prob=0.0)
    risk = RiskConfig()
    s = _samples(400)
    rng = np.random.default_rng(0)
    p_up = rng.uniform(0, 1, len(s))
    log = BinaryBacktestEngine(cfg, risk).run(s, p_up, 0.6)
    m = compute_metrics(log, risk.initial_capital, n_signals=len(s), n_bootstrap=100)
    if m.n_trades:
        assert 0 <= m.win_rate <= 1
        assert m.win_rate_ci_lo <= m.win_rate <= m.win_rate_ci_hi
        r = ruin_probability(log, risk.initial_capital, risk.risk_per_trade,
                             n_paths=200, horizon_trades=200)
        assert 0 <= r.prob_ruin <= 1
