"""CryptOption OTC import provider.

This is the ONLY CryptOption-related data path. It does NOT connect to
CryptOption. It reads a CSV/Parquet file that the user exported themselves and
placed on disk. OTC assets are broker-generated synthetic series, so they are
tagged is_otc=True and market_type=FOREX_OTC and are never pooled with real
markets downstream.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from ..schema import MarketType, NormalizedCandle
from .historical import HistoricalReplayProvider, frame_to_candles, load_candles_frame


def load_otc_import(path: str | Path, asset: str) -> list[NormalizedCandle]:
    df: pl.DataFrame = load_candles_frame(path, default_asset=asset,
                                          market_type=MarketType.FOREX_OTC)
    df = df.with_columns([
        pl.lit(True).alias("is_otc"),
        pl.lit("cryptoption_manual_import").alias("source"),
    ])
    return frame_to_candles(df)


class CryptOptionOtcImportProvider(HistoricalReplayProvider):
    """Replay of a manually-exported OTC file. No network access whatsoever."""

    name = "cryptoption_otc_import"

    def __init__(self, path: str | Path, asset: str, *, speed: float = 0.0):
        super().__init__(load_otc_import(path, asset), speed=speed)
