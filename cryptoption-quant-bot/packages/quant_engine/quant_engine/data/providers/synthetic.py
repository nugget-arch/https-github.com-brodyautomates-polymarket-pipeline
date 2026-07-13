"""Deterministic synthetic provider (random walk with vol clustering).

Reproducible from a seed. `speed` controls wall-clock pacing per tick (0 = as
fast as possible, for tests/backtests). Injects an optional weak AR(1) signal
(`edge_autocorr`) used ONLY as a positive control for downstream detection —
never as a market claim.
"""
from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from ..schema import ConnectionState, MarketType, NormalizedTick
from .base import MarketDataProvider, ProviderCapabilities


class SyntheticMarketDataProvider(MarketDataProvider):
    name = "synthetic"

    def __init__(
        self,
        asset: str = "SYNTH",
        *,
        seed: int = 7,
        start_price: float = 100.0,
        base_vol: float = 3e-4,
        edge_autocorr: float = 0.0,
        interval_seconds: float = 1.0,
        speed: float = 0.0,
        max_ticks: int | None = None,
        start_ts: datetime | None = None,
    ):
        self.asset = asset
        self._rng = random.Random(seed)
        self._price = start_price
        self._base_vol = base_vol
        self._edge = edge_autocorr
        self._interval = interval_seconds
        self._speed = speed
        self._max_ticks = max_ticks
        self._ts = start_ts or datetime(2024, 1, 1, tzinfo=UTC)
        self._vol = base_vol
        self._prev_ret = 0.0
        self._state = ConnectionState.DISCONNECTED

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(trades=True, candles=False, bid_ask=True,
                                    volume=True, backfill=False)

    def state(self) -> ConnectionState:
        return self._state

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    def _next_price(self) -> float:
        self._vol = 0.94 * self._vol + 0.06 * abs(self._prev_ret)
        eps = self._rng.gauss(0, max(self._vol, self._base_vol * 0.25))
        ret = self._edge * self._prev_ret + eps
        self._prev_ret = ret
        self._price = max(0.01, self._price * (1 + ret))
        return self._price

    async def stream_ticks(self) -> AsyncIterator[NormalizedTick]:
        if self._state != ConnectionState.CONNECTED:
            await self.connect()
        n = 0
        while self._max_ticks is None or n < self._max_ticks:
            price = self._next_price()
            half_spread = price * self._base_vol
            yield NormalizedTick(
                ts_utc=self._ts,
                asset=self.asset,
                market_type=MarketType.SYNTHETIC,
                price=price,
                bid=price - half_spread,
                ask=price + half_spread,
                volume=self._rng.uniform(1, 10),
                source="synthetic",
                is_otc=False,
            )
            self._ts += timedelta(seconds=self._interval)
            n += 1
            if self._speed > 0:
                await asyncio.sleep(self._speed)
