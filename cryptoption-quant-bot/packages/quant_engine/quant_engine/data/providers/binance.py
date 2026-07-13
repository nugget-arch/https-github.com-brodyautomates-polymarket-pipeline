"""Binance public-market-data provider (crypto only).

Uses ONLY Binance's public, keyless, official endpoints. No account, no
private data. Some hosts are geo-restricted (HTTP 451); we try a list of
public hosts and fall back gracefully. This provider must never be used for
forex OTC assets — those do not trade on Binance.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ..schema import ConnectionState, MarketType, NormalizedCandle, NormalizedTick, session_id_for
from .base import MarketDataProvider, ProviderCapabilities

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

# Public keyless klines endpoints; tried in order (some are geo-restricted).
KLINES_HOSTS = (
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
)
_INTERVAL = {60: "1m", 300: "5m", 900: "15m", 3600: "1h"}


class BinanceMarketDataProvider(MarketDataProvider):
    name = "binance_public"

    def __init__(self, symbol: str = "BTCUSDT", *, interval_seconds: int = 60,
                 poll_seconds: float = 5.0):
        self.symbol = symbol.upper()
        self.interval_seconds = interval_seconds
        self.poll_seconds = poll_seconds
        self._state = ConnectionState.DISCONNECTED
        self._last_open_time: int | None = None
        self._out_of_order = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(trades=False, candles=True, bid_ask=False,
                                    volume=True, backfill=True)

    def state(self) -> ConnectionState:
        return self._state

    @property
    def out_of_order_count(self) -> int:
        return self._out_of_order

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTING if httpx is None else ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    async def _fetch(self, limit: int) -> list[list]:
        if httpx is None:
            return []
        interval = _INTERVAL.get(self.interval_seconds, "1m")
        params = {"symbol": self.symbol, "interval": interval, "limit": limit}
        async with httpx.AsyncClient(timeout=15) as client:
            for host in KLINES_HOSTS:
                try:
                    r = await client.get(host, params=params)
                    if r.status_code == 200 and isinstance(r.json(), list):
                        return r.json()
                except Exception:
                    continue
        self._state = ConnectionState.ERROR
        return []

    def _row_to_candle(self, row: list) -> NormalizedCandle:
        ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
        return NormalizedCandle(
            ts_utc=ts, asset=self.symbol, market_type=MarketType.CRYPTO_BINANCE,
            open=float(row[1]), high=float(row[2]), low=float(row[3]),
            close=float(row[4]), volume=float(row[5]),
            source="binance_public", is_otc=False, session_id=session_id_for(ts),
        )

    async def backfill_candles(self, start: datetime, end: datetime) -> list[NormalizedCandle]:
        rows = await self._fetch(limit=1000)
        return [c for c in map(self._row_to_candle, rows) if start <= c.ts_utc < end]

    async def stream_ticks(self) -> AsyncIterator[NormalizedTick]:
        """Poll closed klines and emit the latest close as a tick. Drops
        out-of-order bars (counts them) so downstream never sees the past."""
        await self.connect()
        while self._state in (ConnectionState.CONNECTED, ConnectionState.RECONNECTING):
            rows = await self._fetch(limit=2)
            if not rows:
                self._state = ConnectionState.RECONNECTING
                await asyncio.sleep(self.poll_seconds)
                continue
            self._state = ConnectionState.CONNECTED
            closed = rows[-2] if len(rows) >= 2 else rows[-1]
            open_time = int(closed[0])
            if self._last_open_time is not None and open_time <= self._last_open_time:
                if open_time < self._last_open_time:
                    self._out_of_order += 1
                await asyncio.sleep(self.poll_seconds)
                continue
            self._last_open_time = open_time
            c = self._row_to_candle(closed)
            yield NormalizedTick(
                ts_utc=c.ts_utc, asset=c.asset, market_type=c.market_type,
                price=c.close, volume=c.volume, source=c.source, is_otc=False,
            )
            await asyncio.sleep(self.poll_seconds)
