"""Binary-option labels with explicit timing.

Timeline for a signal generated at the close of bar t:
    entry bar   e = t + latency_bars          (entry price = OPEN of bar e)
    expiry bar  x = e + expiry_bars - 1       (expiry price = CLOSE of bar x)

    y = 1 (CALL wins)  if close[x] > open[e]
    y = 0 (PUT  wins)  if close[x] < open[e]
    tie                if close[x] == open[e], handled per config.

`horizon_end = x` is stored per sample so validation can purge any training
sample whose outcome window overlaps a later evaluation window.

Gaps: a sample is only emitted when bars t..x are contiguous in time; labels
never bridge session gaps or missing bars.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import LabelConfig


@dataclass
class LabelSet:
    """Aligned arrays for one (asset, expiry) labelling pass."""

    frame: pd.DataFrame  # columns: signal_idx, entry_idx, horizon_end, entry_price,
    #          expiry_price, y_up, is_tie, asset, expiry_bars, timestamp, session
    expiry_bars: int
    latency_bars: int
    tie_policy: str


def _contiguous(ts: pd.Series, bar_seconds: int, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """True where every bar between positions start..end is exactly bar_seconds apart."""
    # unit-agnostic epoch seconds (pandas may store datetime64 in ns OR us)
    sec = ts.dt.as_unit("s").astype("int64").to_numpy()
    ok = np.ones(len(start), dtype=bool)
    span = end - start
    expected = span * bar_seconds
    ok &= (sec[end] - sec[start]) == expected
    return ok


def build_labels(
    df: pd.DataFrame,
    expiry_bars: int,
    cfg: LabelConfig | None = None,
    bar_seconds: int = 60,
) -> LabelSet:
    """Build labels for every asset in the canonical frame for one expiry."""
    cfg = cfg or LabelConfig()
    lat = cfg.latency_bars
    parts: list[pd.DataFrame] = []

    for asset, g in df.groupby("asset", sort=False):
        g = g.reset_index(drop=True)
        n = len(g)
        # positions (0-based within asset) of signal bars that fit the horizon
        last_signal = n - (lat + expiry_bars) - 1
        if last_signal < 0:
            continue
        t = np.arange(0, last_signal + 1)
        e = t + lat
        x = e + expiry_bars - 1

        entry_price = g["open"].to_numpy()[e]
        expiry_price = g["close"].to_numpy()[x]

        contiguous = _contiguous(g["timestamp"], bar_seconds, t, x)

        y_up = (expiry_price > entry_price).astype(np.int8)
        is_tie = expiry_price == entry_price

        part = pd.DataFrame({
            "asset": asset,
            "signal_idx": t,
            "entry_idx": e,
            "horizon_end": x,
            "timestamp": g["timestamp"].to_numpy()[t],
            "session": g["session"].to_numpy()[t],
            "is_otc": g["is_otc"].to_numpy()[t],
            "entry_price": entry_price,
            "expiry_price": expiry_price,
            "y_up": y_up,
            "is_tie": is_tie,
        })
        part = part[contiguous]

        if cfg.tie_policy == "drop":
            part = part[~part["is_tie"]]
        # "refund"/"loss" ties stay in the frame; the backtest settles them.
        parts.append(part)

    frame = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["asset", "signal_idx", "entry_idx", "horizon_end",
                                   "timestamp", "session", "is_otc", "entry_price",
                                   "expiry_price", "y_up", "is_tie"])
    )
    return LabelSet(frame=frame, expiry_bars=expiry_bars,
                    latency_bars=lat, tie_policy=cfg.tie_policy)
