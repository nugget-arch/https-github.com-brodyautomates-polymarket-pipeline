"""Synthetic sample data for tests and demos.

Two flavours per run:
  * an "OTC-like" asset (24/7 sessions, e.g. EURUSD_OTC),
  * a "regular" asset (weekday sessions only, e.g. GBPUSD).

Price model: geometric random walk with mild GARCH-ish volatility clustering
and optional injected inefficiency (`edge_bps` autocorrelation) so tests can
verify the platform *can* detect an edge when one truly exists. Default
edge_bps=0 → an honest platform must conclude there is no edge.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _walk(
    rng: np.random.Generator,
    n: int,
    start_price: float,
    base_vol: float,
    edge_autocorr: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return open/high/low/close arrays for an n-bar series."""
    rets = np.empty(n)
    vol = base_vol
    prev = 0.0
    for i in range(n):
        # volatility clustering: EWMA of squared returns
        vol = 0.94 * vol + 0.06 * abs(prev)
        eps = rng.standard_normal() * max(vol, base_vol * 0.25)
        rets[i] = edge_autocorr * prev + eps  # AR(1); 0 => pure noise
        prev = rets[i]

    closes = start_price * np.exp(np.cumsum(rets))
    opens = np.concatenate([[start_price], closes[:-1]])
    intrabar = np.abs(rng.standard_normal(n)) * base_vol * 0.5
    highs = np.maximum(opens, closes) * (1 + intrabar)
    lows = np.minimum(opens, closes) * (1 - intrabar)
    return opens, highs, lows, closes


def make_asset_frame(
    asset: str,
    n_bars: int,
    bar_seconds: int = 60,
    seed: int = 7,
    start: str = "2024-01-01",
    is_otc: bool = False,
    weekdays_only: bool = False,
    edge_autocorr: float = 0.0,
    base_vol: float = 3e-4,
    start_price: float = 1.10,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    o, h, l, c = _walk(rng, n_bars, start_price, base_vol, edge_autocorr)

    ts = pd.date_range(start=start, periods=n_bars, freq=f"{bar_seconds}s", tz="UTC")
    df = pd.DataFrame({
        "timestamp": ts, "asset": asset,
        "open": o, "high": h, "low": l, "close": c,
        "volume": rng.uniform(10, 100, n_bars),
        "is_otc": is_otc,
    })
    if weekdays_only:
        df = df[df["timestamp"].dt.dayofweek < 5].reset_index(drop=True)
    df["session"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    return df


def generate_synthetic_dataset(
    out_dir: str | Path,
    n_bars: int = 30_000,
    seed: int = 7,
    edge_autocorr: float = 0.0,
) -> list[Path]:
    """Write two sample parquet files (OTC-like and regular). Returns paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    otc = make_asset_frame(
        "EURUSD_OTC", n_bars, seed=seed, is_otc=True,
        weekdays_only=False, edge_autocorr=edge_autocorr,
    )
    reg = make_asset_frame(
        "GBPUSD", n_bars, seed=seed + 1, is_otc=False,
        weekdays_only=True, edge_autocorr=0.0, start_price=1.27,
    )

    p1 = out / "eurusd_otc_1m.parquet"
    p2 = out / "gbpusd_1m.parquet"
    otc.to_parquet(p1, index=False)
    reg.to_parquet(p2, index=False)
    return [p1, p2]
