"""Causal feature engineering.

CONTRACT: every feature at row t uses ONLY bars <= t (each bar being fully
closed). All rolling/EWM operations in pandas are backward-looking, and the
no-lookahead property is enforced by `tests/test_features.py` (truncation
invariance: recomputing on a truncated series must reproduce the last row).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FeatureConfig

FEATURE_PREFIX = "f_"


def _rolling_slope(y: pd.Series, window: int) -> pd.Series:
    """OLS slope of y against 0..w-1 over a rolling window (causal),
    normalised by the window mean so it is scale-free across assets."""
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def slope(vals: np.ndarray) -> float:
        m = vals.mean()
        if m == 0:
            return 0.0
        return float(((x - x_mean) * (vals - vals.mean())).sum() / x_var / m)

    return y.rolling(window).apply(slope, raw=True)


def _asset_features(g: pd.DataFrame, cfg: FeatureConfig) -> pd.DataFrame:
    out = pd.DataFrame(index=g.index)
    close, high, low, open_ = g["close"], g["high"], g["low"], g["open"]

    # log returns
    logret = np.log(close / close.shift(1))
    out[f"{FEATURE_PREFIX}logret_1"] = logret

    # momentum: k-bar log return
    for k in cfg.momentum_windows:
        out[f"{FEATURE_PREFIX}mom_{k}"] = np.log(close / close.shift(k))

    # EMAs and normalised distance between them
    ema_fast = close.ewm(span=cfg.ema_fast, adjust=False).mean()
    ema_slow = close.ewm(span=cfg.ema_slow, adjust=False).mean()
    out[f"{FEATURE_PREFIX}ema_dist"] = (ema_fast - ema_slow) / close
    out[f"{FEATURE_PREFIX}close_vs_ema_fast"] = (close - ema_fast) / close

    # RSI (Wilder, causal EWM)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    rs = gain / loss.replace(0.0, np.nan)
    out[f"{FEATURE_PREFIX}rsi"] = (100 - 100 / (1 + rs)).fillna(50.0) / 100.0

    # ATR (normalised) and realized volatility
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / cfg.atr_period, adjust=False).mean()
    out[f"{FEATURE_PREFIX}atr_norm"] = atr / close
    out[f"{FEATURE_PREFIX}realized_vol"] = logret.rolling(cfg.realized_vol_window).std()

    # Bollinger z-score
    mid = close.rolling(cfg.bollinger_window).mean()
    sd = close.rolling(cfg.bollinger_window).std()
    out[f"{FEATURE_PREFIX}bb_z"] = (close - mid) / sd.replace(0.0, np.nan)

    # regression slope of close
    out[f"{FEATURE_PREFIX}slope"] = _rolling_slope(close, cfg.slope_window)

    # candle anatomy (current, fully closed bar)
    rng = (high - low).replace(0.0, np.nan)
    out[f"{FEATURE_PREFIX}range_norm"] = (high - low) / close
    out[f"{FEATURE_PREFIX}body_frac"] = ((close - open_) / rng).fillna(0.0)

    # cyclic time-of-day / day-of-week
    ts = g["timestamp"]
    minute_of_day = ts.dt.hour * 60 + ts.dt.minute
    out[f"{FEATURE_PREFIX}tod_sin"] = np.sin(2 * np.pi * minute_of_day / 1440.0)
    out[f"{FEATURE_PREFIX}tod_cos"] = np.cos(2 * np.pi * minute_of_day / 1440.0)
    dow = ts.dt.dayofweek
    out[f"{FEATURE_PREFIX}dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    out[f"{FEATURE_PREFIX}dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    return out


def build_features(df: pd.DataFrame, cfg: FeatureConfig | None = None) -> pd.DataFrame:
    """Compute features per asset (never across asset boundaries).

    Returns the input frame with `f_*` columns appended. Rows inside each
    asset's warm-up window contain NaNs — downstream code must drop them, they
    are NOT filled (filling would import information across gaps).
    """
    cfg = cfg or FeatureConfig()
    feats = (
        df.groupby("asset", sort=False, group_keys=False)
        .apply(lambda g: _asset_features(g, cfg), include_groups=False)
    )
    out = pd.concat([df.reset_index(drop=True), feats.reset_index(drop=True)], axis=1)
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith(FEATURE_PREFIX)]
