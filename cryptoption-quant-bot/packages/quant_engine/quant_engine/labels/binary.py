"""Binary-option labels with explicit timing.

Signal at the close of bar t:
    entry bar   e = t + latency_bars       (entry price = OPEN of bar e)
    expiry bar  x = e + expiry_bars - 1     (expiry price = CLOSE of bar x)

    y_up = 1 (CALL wins) if close[x] > open[e]
    y_up = 0 (PUT  wins) if close[x] < open[e]
    tie              if close[x] == open[e] (handled per policy)

`horizon_end = x` per sample lets validation purge overlapping outcomes. A
sample is emitted ONLY when bars t..x are contiguous (no gap / no session
cross): the label never bridges missing data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import LabelConfig


@dataclass
class LabelSet:
    frame: pd.DataFrame
    expiry_bars: int
    latency_bars: int
    tie_policy: str


def _epoch_seconds(ts: pd.Series) -> np.ndarray:
    return (ts.dt.tz_convert("UTC").dt.as_unit("s").astype("int64")).to_numpy()


def build_labels(
    df: pd.DataFrame,
    expiry_bars: int,
    cfg: LabelConfig | None = None,
    bar_seconds: int = 60,
) -> LabelSet:
    cfg = cfg or LabelConfig()
    lat = cfg.latency_bars
    parts: list[pd.DataFrame] = []

    for asset, g in df.sort_values(["asset", "ts_utc"]).groupby("asset", sort=False):
        g = g.reset_index(drop=True)
        n = len(g)
        last_signal = n - (lat + expiry_bars) - 1
        if last_signal < 0:
            continue
        t = np.arange(0, last_signal + 1)
        e = t + lat
        x = e + expiry_bars - 1

        entry_price = g["open"].to_numpy()[e]
        expiry_price = g["close"].to_numpy()[x]

        sec = _epoch_seconds(g["ts_utc"])
        contiguous = (sec[x] - sec[t]) == (x - t) * bar_seconds
        same_session = g["session_id"].to_numpy()[t] == g["session_id"].to_numpy()[x] \
            if "session_id" in g.columns else np.ones(len(t), dtype=bool)

        y_up = (expiry_price > entry_price).astype(np.int8)
        is_tie = expiry_price == entry_price

        part = pd.DataFrame({
            "asset": asset,
            "signal_idx": t,
            "entry_idx": e,
            "horizon_end": x,
            "ts_utc": g["ts_utc"].to_numpy()[t],
            "session_id": g["session_id"].to_numpy()[t] if "session_id" in g.columns else "",
            "is_otc": g["is_otc"].to_numpy()[t] if "is_otc" in g.columns else False,
            "entry_price": entry_price,
            "expiry_price": expiry_price,
            "y_up": y_up,
            "is_tie": is_tie,
        })
        part = part[contiguous & same_session]
        if cfg.tie_policy == "EXCLUDE":
            part = part[~part["is_tie"]]
        parts.append(part)

    cols = ["asset", "signal_idx", "entry_idx", "horizon_end", "ts_utc", "session_id",
            "is_otc", "entry_price", "expiry_price", "y_up", "is_tie"]
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
    return LabelSet(frame=frame, expiry_bars=expiry_bars,
                    latency_bars=lat, tie_policy=cfg.tie_policy)
