"""Candle ingestion from CSV/Parquet into a canonical frame.

Canonical schema (one row per bar, one frame may hold many assets):
    timestamp  datetime64[ns, UTC]   bar OPEN time
    asset      str                   e.g. "EURUSD_OTC"
    open/high/low/close  float64
    volume     float64 (0.0 if source has none)
    is_otc     bool                  derived from asset name or explicit column
    session    str                   trading date (UTC) used for daily risk limits

Convention used across the whole platform: a bar with timestamp T covers
[T, T + bar_seconds). All information in the bar is only *available* at its
close, T + bar_seconds. Decisions at "bar t" mean "at the close of bar t".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import DataConfig
from ..logging_setup import get_logger

log = get_logger("data.loader")

CANDLE_COLUMNS = ["timestamp", "asset", "open", "high", "low", "close", "volume", "is_otc", "session"]

_RENAMES = {
    "time": "timestamp", "date": "timestamp", "datetime": "timestamp",
    "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
    "symbol": "asset", "pair": "asset", "ticker": "asset",
}


def _read_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {path} (use .csv or .parquet)")


def _is_otc_asset(asset: str, cfg: DataConfig) -> bool:
    low = asset.lower()
    return any(low.endswith(sfx) or sfx.strip() in low.split("_") for sfx in cfg.otc_suffixes)


def load_candles(paths: list[str | Path], cfg: DataConfig | None = None) -> pd.DataFrame:
    """Load and concatenate candle files into the canonical schema.

    OTC and regular markets are identified separately via `is_otc` so they are
    never pooled by accident in downstream analysis.
    """
    cfg = cfg or DataConfig()
    frames: list[pd.DataFrame] = []
    for p in paths:
        path = Path(p)
        df = _read_any(path)
        df = df.rename(columns={c: _RENAMES.get(c.lower(), c.lower()) for c in df.columns})

        if "asset" not in df.columns:
            df["asset"] = path.stem.upper()
        if "volume" not in df.columns:
            df["volume"] = 0.0

        missing = {"timestamp", "open", "high", "low", "close"} - set(df.columns)
        if missing:
            raise ValueError(f"{path}: missing required columns {sorted(missing)}")

        ts = pd.to_datetime(df["timestamp"], utc=False, errors="coerce")
        if ts.isna().any():
            raise ValueError(f"{path}: {int(ts.isna().sum())} unparseable timestamps")
        # normalise timezone: naive stamps are declared as cfg.timezone, then converted to UTC
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize(cfg.timezone)
        df["timestamp"] = ts.dt.tz_convert("UTC")

        if "is_otc" not in df.columns:
            df["is_otc"] = df["asset"].astype(str).map(lambda a: _is_otc_asset(a, cfg))
        df["is_otc"] = df["is_otc"].astype(bool)

        df["asset"] = df["asset"].astype(str).str.upper()
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

        df["session"] = df["timestamp"].dt.strftime("%Y-%m-%d")
        frames.append(df[CANDLE_COLUMNS])
        log.info("loaded file", extra={"ctx_path": str(path), "ctx_rows": len(df)})

    if not frames:
        raise ValueError("no data files provided")
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["asset", "timestamp"], kind="stable").reset_index(drop=True)
    return out


def split_holdout(df: pd.DataFrame, cfg: DataConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split off the FINAL `holdout_fraction` of each asset's history.

    The holdout is the fully blocked final test: it must not be touched during
    development. `research` is everything you may look at.
    """
    research_parts: list[pd.DataFrame] = []
    holdout_parts: list[pd.DataFrame] = []
    for _, g in df.groupby("asset", sort=False):
        cut = int(len(g) * (1.0 - cfg.holdout_fraction))
        research_parts.append(g.iloc[:cut])
        holdout_parts.append(g.iloc[cut:])
    research = pd.concat(research_parts, ignore_index=True)
    holdout = pd.concat(holdout_parts, ignore_index=True)
    return research, holdout
