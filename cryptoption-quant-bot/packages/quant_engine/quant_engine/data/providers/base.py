"""MarketDataProvider interface.

Providers are async iterables of normalized ticks/candles. They expose an
explicit connection state and the capability to backfill after a gap. Only
public/official or local sources are permitted — never a private, reverse
engineered CryptOption endpoint.
"""
from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from ..schema import ConnectionState, NormalizedCandle, NormalizedTick


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    trades: bool
    candles: bool
    bid_ask: bool
    volume: bool
    backfill: bool


class MarketDataProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abc.abstractmethod
    def state(self) -> ConnectionState: ...

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @abc.abstractmethod
    def stream_ticks(self) -> AsyncIterator[NormalizedTick]:
        """Yield ticks in non-decreasing ts order. Out-of-order ticks must be
        dropped by the provider and surfaced via a quality counter."""
        ...

    async def backfill_candles(
        self, start: datetime, end: datetime
    ) -> list[NormalizedCandle]:
        """Return closed candles in [start, end) after a disconnection.
        Default: unsupported."""
        return []
