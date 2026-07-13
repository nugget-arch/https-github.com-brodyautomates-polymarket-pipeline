"""Engine configuration dataclasses (pure Python, no web deps)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class FeatureConfig:
    return_horizons: tuple[int, ...] = (1, 5, 10, 15, 30, 60)
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    realized_vol_window: int = 20
    bollinger_window: int = 20
    slope_window: int = 12
    volume_window: int = 20
    regime_window: int = 60


@dataclass(frozen=True)
class LabelConfig:
    expiry_bars: tuple[int, ...] = (1, 2, 3, 5)
    latency_bars: int = 1
    tie_policy: Literal["LOSS", "TIE", "EXCLUDE"] = "TIE"


@dataclass(frozen=True)
class StrategyConfig:
    logistic_c: float = 0.1
    calibration: Literal["sigmoid", "isotonic", "none"] = "sigmoid"
    feature_names: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BacktestConfig:
    payout_base: float = 0.80
    payout_jitter: float = 0.05      # per-trade payout ~ U(base±jitter)
    payout_floor: float = 0.70
    rejection_prob: float = 0.02     # broker refuses this fraction of entries
    threshold_margin: float = 0.02   # safety margin over break-even win rate
    threshold_use_val_ci: bool = True
    slippage_prob: float = 0.0       # chance entry price differs from expected
    tie_policy: Literal["LOSS", "TIE", "EXCLUDE"] = "TIE"


@dataclass(frozen=True)
class RiskConfig:
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.0025   # 0.25% default
    max_risk_per_trade: float = 0.005  # hard cap 0.50%
    daily_loss_limit: float = 0.01   # 1% of capital
    max_consecutive_losses: int = 3
    cooldown_bars: int = 60
    max_trades_per_session: int = 50
    drawdown_soft_limit: float = 0.05
    drawdown_scale: float = 0.5      # stake multiplier while in soft drawdown
    min_stake: float = 1.0

    def __post_init__(self) -> None:
        if self.risk_per_trade > 0.005:
            raise ValueError("risk_per_trade must be <= 0.005 (0.5%)")
