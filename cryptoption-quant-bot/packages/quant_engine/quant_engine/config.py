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
