"""Historical providers: CSV/Parquet loaders and a deterministic replayer.

The replayer feeds stored candles in chronological order through a simulated
clock, so a research run is byte-for-byte reproducible. Loading uses Polars
(fast ingestion path); the candles are emitted as close-price ticks.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import polars as pl

from ..schema import ConnectionState, MarketType, NormalizedCandle, NormalizedTick, session_id_for
from .base import MarketDataProvider, ProviderCapabilities

_RENAMES = {
    "time": "ts_utc", "timestamp": "ts_utc", "date": "ts_utc", "datetime": "ts_utc",
    "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
    "symbol": "asset", "pair": "asset",
}


def load_candles_frame(path: str | Path, default_asset: str | None = None,
                       market_type: MarketType = MarketType.NORMAL) -> pl.DataFrame:
    """Load CSV/Parquet into a canonical Polars candle frame (no future fill)."""
    p = Path(path)
    if p.suffix.lower() in {".parquet", ".pq"}:
        df = pl.read_parquet(p)
    elif p.suffix.lower() == ".csv":
        df = pl.read_csv(p, try_parse_dates=True)
    else:
        raise ValueError(f"unsupported file type: {p}")

    df = df.rename({c: _RENAMES.get(c.lower(), c.lower()) for c in df.columns})
    if "asset" not in df.columns:
        df = df.with_columns(pl.lit(default_asset or p.stem.upper()).alias("asset"))
    if "volume" not in df.columns:
        df = df.with_columns(pl.lit(0.0).alias("volume"))
    missing = {"ts_utc", "open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"{p}: missing required columns {sorted(missing)}")

    df = df.with_columns(pl.col("ts_utc").cast(pl.Datetime(time_zone="UTC")))
    df = df.with_columns(pl.lit(market_type.value).alias("market_type"))
    return df.sort(["asset", "ts_utc"])


def frame_to_candles(df: pl.DataFrame) -> list[NormalizedCandle]:
    candles: list[NormalizedCandle] = []
    for row in df.iter_rows(named=True):
        mt = MarketType(row.get("market_type", MarketType.NORMAL.value))
        ts = row["ts_utc"]
        candles.append(NormalizedCandle(
            ts_utc=ts, asset=row["asset"], market_type=mt,
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
            bid=row.get("bid"), ask=row.get("ask"),
            source=str(row.get("source", "historical")),
            is_otc=bool(row.get("is_otc", mt == MarketType.FOREX_OTC)),
            session_id=session_id_for(ts),
        ))
    return candles


class HistoricalReplayProvider(MarketDataProvider):
    """Replays a list of candles as close-price ticks, in order, with an
    optional simulated pacing. Fully deterministic."""

    name = "historical_replay"

    def __init__(self, candles: list[NormalizedCandle], *, speed: float = 0.0):
        self._candles = sorted(candles, key=lambda c: c.ts_utc)
        self._speed = speed
        self._state = ConnectionState.DISCONNECTED

    @classmethod
    def from_file(cls, path: str | Path, *, market_type: MarketType = MarketType.NORMAL,
                  speed: float = 0.0) -> HistoricalReplayProvider:
        return cls(frame_to_candles(load_candles_frame(path, market_type=market_type)),
                   speed=speed)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(trades=True, candles=True, bid_ask=False,
                                    volume=True, backfill=True)

    def state(self) -> ConnectionState:
        return self._state

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    async def stream_ticks(self) -> AsyncIterator[NormalizedTick]:
        await self.connect()
        for c in self._candles:
            yield NormalizedTick(
                ts_utc=c.ts_utc, asset=c.asset, market_type=c.market_type,
                price=c.close, bid=c.bid, ask=c.ask, volume=c.volume,
                source=c.source, is_otc=c.is_otc,
            )
            if self._speed > 0:
                await asyncio.sleep(self._speed)

    async def backfill_candles(self, start: datetime, end: datetime) -> list[NormalizedCandle]:
        return [c for c in self._candles if start <= c.ts_utc < end]
