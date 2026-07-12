import pytest

from otc_lab.config import RiskConfig
from otc_lab.risk.manager import RiskManager


def _mgr(**kw):
    return RiskManager(RiskConfig(**kw))


def test_default_stake_is_quarter_percent():
    m = _mgr(initial_capital=10_000)
    d = m.pre_trade("2024-01-01", 0)
    assert d.allowed and d.stake == pytest.approx(25.0)


def test_risk_fraction_hard_cap():
    with pytest.raises(Exception):
        RiskConfig(risk_per_trade=0.01)  # > 0.5% must be rejected


def test_daily_loss_limit_halts_session():
    m = _mgr(initial_capital=10_000, daily_loss_limit=0.01)
    bar = 0
    while True:
        d = m.pre_trade("2024-01-01", bar)
        if not d.allowed:
            break
        m.settle(d.stake, -d.stake)
        m._consecutive_losses = 0  # isolate the daily-loss guard
        bar += 1
    assert d.reason == "daily_loss_limit"
    assert m._session_pnl <= -100.0
    # new session resets
    assert m.pre_trade("2024-01-02", bar + 1).allowed


def test_three_consecutive_losses_pause():
    m = _mgr(max_consecutive_losses=3, cooldown_bars=60)
    for bar in range(3):
        d = m.pre_trade("2024-01-01", bar)
        assert d.allowed
        m.settle(d.stake, -d.stake)
    d = m.pre_trade("2024-01-01", 3)
    assert not d.allowed and d.reason == "max_consecutive_losses"
    assert not m.pre_trade("2024-01-01", 10).allowed  # cooldown active
    assert m.pre_trade("2024-01-01", 3 + 61).allowed  # after cooldown


def test_session_trade_cap():
    m = _mgr(max_trades_per_session=2)
    for bar in range(2):
        d = m.pre_trade("2024-01-01", bar)
        m.settle(d.stake, d.stake * 0.8)
    d = m.pre_trade("2024-01-01", 5)
    assert not d.allowed and d.reason == "session_trade_cap"


def test_kill_switch():
    m = _mgr()
    m.kill("test")
    assert not m.pre_trade("2024-01-01", 0).allowed


def test_no_martingale_stake_never_grows_after_loss():
    """THE anti-martingale property: after any loss, the next stake must be
    less than or equal to the previous one (capital fell; fraction is fixed
    or reduced — never raised to 'recover')."""
    m = _mgr(initial_capital=10_000, max_consecutive_losses=10**9,
             daily_loss_limit=0.99, max_trades_per_session=10**9)
    prev_stake = None
    for bar in range(200):
        d = m.pre_trade("2024-01-01", bar)
        if not d.allowed:
            break
        if prev_stake is not None:
            assert d.stake <= prev_stake + 1e-9, "stake grew after a loss (martingale!)"
        prev_stake = d.stake
        m.settle(d.stake, -d.stake)


def test_drawdown_reduces_exposure():
    m = _mgr(initial_capital=10_000, drawdown_soft_limit=0.05, drawdown_scale=0.5,
             max_consecutive_losses=10**9, daily_loss_limit=0.99,
             max_trades_per_session=10**9)
    d0 = m.pre_trade("2024-01-01", 0)
    m.settle(d0.stake, -600.0)  # 6% drawdown
    d1 = m.pre_trade("2024-01-01", 1)
    expected = round(m.capital * 0.0025 * 0.5, 2)
    assert d1.stake == pytest.approx(expected)
