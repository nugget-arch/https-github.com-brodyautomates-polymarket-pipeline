"""Causal feature engineering (pandas).

CONTRACT: every feature at row t uses ONLY bars <= t (each fully closed). All
rolling/EWM ops are backward-looking. The no-lookahead property is enforced by
`tests/test_leakage.py` via truncation invariance: recomputing on the series
truncated at t must reproduce row t exactly. Features are computed per asset;
they never cross an asset boundary.

Input frame columns: ts_utc, asset, open, high, low, close, volume, and
optionally bid/ask/spread. Output: same frame with `f_*` columns appended.
Warm-up rows contain NaN and MUST be dropped downstream — never filled (filling
would import information across gaps).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FeatureConfig

FEATURE_PREFIX = "f_"


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith(FEATURE_PREFIX)]


def _rolling_slope(y: pd.Series, window: int) -> pd.Series:
    """Scale-free OLS slope of y over a causal rolling window."""
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
    p = FEATURE_PREFIX

    # log returns + multi-horizon returns
    logret = np.log(close / close.shift(1))
    out[f"{p}logret_1"] = logret
    for k in cfg.return_horizons:
        out[f"{p}ret_{k}"] = np.log(close / close.shift(k))
        out[f"{p}mom_{k}"] = close.pct_change(k)

    # EMAs, distance, and EMA slope
    ema_fast = close.ewm(span=cfg.ema_fast, adjust=False).mean()
    ema_slow = close.ewm(span=cfg.ema_slow, adjust=False).mean()
    out[f"{p}ema_dist"] = (ema_fast - ema_slow) / close
    out[f"{p}ema_fast_slope"] = ema_fast.diff() / close
    out[f"{p}close_vs_ema_fast"] = (close - ema_fast) / close

    # RSI (Wilder, causal EWM)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    rs = gain / loss.replace(0.0, np.nan)
    out[f"{p}rsi"] = (100 - 100 / (1 + rs)).fillna(50.0) / 100.0

    # ATR (normalised) and realized volatility
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / cfg.atr_period, adjust=False).mean()
    out[f"{p}atr_norm"] = atr / close
    out[f"{p}realized_vol"] = logret.rolling(cfg.realized_vol_window).std()

    # Bollinger z-score
    mid = close.rolling(cfg.bollinger_window).mean()
    sd = close.rolling(cfg.bollinger_window).std()
    out[f"{p}bb_z"] = (close - mid) / sd.replace(0.0, np.nan)

    # regression slope of close
    out[f"{p}slope"] = _rolling_slope(close, cfg.slope_window)

    # candle anatomy (current, fully-closed bar)
    rng = (high - low).replace(0.0, np.nan)
    out[f"{p}range_norm"] = (high - low) / close
    out[f"{p}body_frac"] = ((close - open_) / rng).fillna(0.0)
    out[f"{p}upper_wick"] = ((high - np.maximum(open_, close)) / rng).fillna(0.0)
    out[f"{p}lower_wick"] = ((np.minimum(open_, close) - low) / rng).fillna(0.0)
    out[f"{p}close_pos_in_range"] = ((close - low) / rng).fillna(0.5)

    # volume-based
    vol = g["volume"].astype(float)
    vol_mean = vol.rolling(cfg.volume_window).mean()
    out[f"{p}volume_rel"] = (vol / vol_mean.replace(0.0, np.nan)).fillna(1.0)
    # order-flow PROXIES (no trade-level data): signed by candle direction.
    signed = np.sign(close - open_)
    out[f"{p}trade_imbalance_proxy"] = (signed * out[f"{p}body_frac"]).fillna(0.0)
    out[f"{p}trade_intensity_proxy"] = (vol / vol.rolling(cfg.volume_window).median()
                                        .replace(0.0, np.nan)).fillna(1.0)

    # spread (if quotes available), else neutral
    if "spread" in g.columns and g["spread"].notna().any():
        spread = g["spread"].astype(float)
    elif {"bid", "ask"}.issubset(g.columns):
        spread = (g["ask"] - g["bid"]).astype(float)
    else:
        spread = pd.Series(np.nan, index=g.index)
    out[f"{p}spread_norm"] = (spread / close).fillna(0.0)
    out[f"{p}spread_change"] = spread.diff().div(close).fillna(0.0)

    # cyclic time features
    ts = g["ts_utc"]
    minute_of_day = ts.dt.hour * 60 + ts.dt.minute
    out[f"{p}tod_sin"] = np.sin(2 * np.pi * minute_of_day / 1440.0)
    out[f"{p}tod_cos"] = np.cos(2 * np.pi * minute_of_day / 1440.0)
    dow = ts.dt.dayofweek
    out[f"{p}dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    out[f"{p}dow_cos"] = np.cos(2 * np.pi * dow / 7.0)

    # regimes (CAUSAL: relative to backward-looking stats, never global terciles)
    rv = out[f"{p}realized_vol"]
    rv_mean = rv.rolling(cfg.regime_window).mean()
    rv_std = rv.rolling(cfg.regime_window).std().replace(0.0, np.nan)
    out[f"{p}vol_regime_z"] = ((rv - rv_mean) / rv_std).fillna(0.0)
    out[f"{p}trend_regime"] = np.sign(out[f"{p}ema_dist"]).fillna(0.0)
    return out


def build_features(df: pd.DataFrame, cfg: FeatureConfig | None = None) -> pd.DataFrame:
    """Compute `f_*` features per asset. Input must be sorted by ts within asset."""
    cfg = cfg or FeatureConfig()
    df = df.sort_values(["asset", "ts_utc"]).reset_index(drop=True)
    feats = (
        df.groupby("asset", sort=False, group_keys=False)
        .apply(lambda g: _asset_features(g, cfg), include_groups=False)
    )
    return pd.concat([df.reset_index(drop=True), feats.reset_index(drop=True)], axis=1)
