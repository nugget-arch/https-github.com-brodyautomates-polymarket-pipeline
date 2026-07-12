"""Causal OHLC resampling.

A resampled bar labelled T aggregates source bars in [T, T + period). Its
information is complete only at T + period. To keep the "decide at bar close"
convention safe, we also emit `available_at` = T + period so downstream code
never uses a resampled bar before it is finished.
"""
from __future__ import annotations

import pandas as pd


def resample_ohlc(df: pd.DataFrame, target_seconds: int, source_seconds: int) -> pd.DataFrame:
    """Resample canonical candles to a coarser timeframe, per asset.

    Only *complete* target bars are kept (a trailing partial bar is dropped),
    which is what prevents look-ahead: you can never see a half-built bar.
    """
    if target_seconds % source_seconds != 0:
        raise ValueError("target must be a multiple of source bar size")
    if target_seconds == source_seconds:
        return df.copy()

    rule = f"{target_seconds}s"
    bars_per_target = target_seconds // source_seconds
    out_parts: list[pd.DataFrame] = []

    for asset, g in df.groupby("asset", sort=False):
        g = g.set_index("timestamp").sort_index()
        agg = g.resample(rule, label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            n_src=("close", "count"),
        )
        # keep only fully-formed bars — a partial bar would leak the future
        agg = agg[agg["n_src"] == bars_per_target].drop(columns="n_src")
        agg = agg.dropna(subset=["open", "high", "low", "close"])
        agg["asset"] = asset
        agg["is_otc"] = bool(g["is_otc"].iloc[0])
        agg = agg.reset_index()
        agg["session"] = agg["timestamp"].dt.strftime("%Y-%m-%d")
        agg["available_at"] = agg["timestamp"] + pd.Timedelta(seconds=target_seconds)
        out_parts.append(agg)

    out = pd.concat(out_parts, ignore_index=True)
    return out[["timestamp", "asset", "open", "high", "low", "close", "volume",
                "is_otc", "session", "available_at"]]
