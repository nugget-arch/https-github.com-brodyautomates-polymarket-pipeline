"""Market feed manager.

Runs a MarketDataProvider as a background task, aggregates ticks into causal
candles, keeps a small ring buffer for REST state-recovery, and publishes
`market.tick` / `market.candle` / `connection.status` messages on the event
bus. Synthetic feed is the Phase-2 default (no network).
"""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import Any

from quant_engine.data import (
    CandleAggregator,
    MarketDataProvider,
    NormalizedCandle,
    NormalizedTick,
    SyntheticMarketDataProvider,
)

from ..logging_setup import get_logger
from ..ws.bus import EventBus, get_bus
from ..ws.events import (
    ConnectionStatusPayload,
    MarketCandlePayload,
    MarketTickPayload,
)

log = get_logger("market_feed")


def tick_channel(asset: str) -> str:
    return f"market:{asset}"


class MarketFeed:
    def __init__(
        self,
        asset: str,
        provider: MarketDataProvider,
        *,
        bar_seconds: int = 60,
        bus: EventBus | None = None,
        candle_buffer: int = 240,
    ):
        self.asset = asset
        self.provider = provider
        self.bus = bus or get_bus()
        self._agg = CandleAggregator(bar_seconds=bar_seconds)
        self._task: asyncio.Task[None] | None = None
        self._last_price: float | None = None
        self._candles: deque[NormalizedCandle] = deque(maxlen=candle_buffer)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_price(self) -> float | None:
        return self._last_price

    def recent_candles(self, limit: int = 120) -> list[dict[str, Any]]:
        items = list(self._candles)[-limit:]
        return [self._candle_payload(c, closed=True).model_dump() for c in items]

    def _tick_payload(self, t: NormalizedTick) -> MarketTickPayload:
        return MarketTickPayload(
            asset=t.asset, market_type=t.market_type.value, ts_utc=t.ts_utc.isoformat(),
            price=t.price, bid=t.bid, ask=t.ask, spread=t.spread,
        )

    def _candle_payload(self, c: NormalizedCandle, *, closed: bool) -> MarketCandlePayload:
        return MarketCandlePayload(
            asset=c.asset, market_type=c.market_type.value, ts_utc=c.ts_utc.isoformat(),
            open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume,
            closed=closed,
        )

    async def _publish(self, type_: str, payload: dict[str, Any]) -> None:
        await self.bus.publish(tick_channel(self.asset), {"type": type_, "payload": payload})

    async def _run(self) -> None:
        status = ConnectionStatusPayload(state=self.provider.state().value, asset=self.asset)
        await self._publish("connection.status", status.model_dump())
        try:
            async for tick in self.provider.stream_ticks():
                self._last_price = tick.price
                await self._publish("market.tick", self._tick_payload(tick).model_dump())
                closed = self._agg.update(tick)
                if closed is not None:
                    self._candles.append(closed)
                    await self._publish("market.candle",
                                        self._candle_payload(closed, closed=True).model_dump())
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("feed_error", asset=self.asset, error=str(e))
            await self._publish("connection.status",
                                ConnectionStatusPayload(state="ERROR", asset=self.asset,
                                                        detail=str(e)).model_dump())

    async def start(self) -> None:
        if self.running:
            return
        await self.provider.connect()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.provider.disconnect()


class MarketFeedManager:
    """One feed per asset, shared across WS connections."""

    def __init__(self) -> None:
        self._feeds: dict[str, MarketFeed] = {}

    async def ensure(self, asset: str, *, bar_seconds: int = 60,
                     speed: float = 1.0) -> MarketFeed:
        feed = self._feeds.get(asset)
        if feed is None:
            provider = SyntheticMarketDataProvider(asset=asset, interval_seconds=1,
                                                   speed=speed)
            feed = MarketFeed(asset, provider, bar_seconds=bar_seconds)
            self._feeds[asset] = feed
        if not feed.running:
            await feed.start()
        return feed

    def get(self, asset: str) -> MarketFeed | None:
        return self._feeds.get(asset)

    async def stop_all(self) -> None:
        for feed in self._feeds.values():
            await feed.stop()
        self._feeds.clear()


_manager: MarketFeedManager | None = None


def get_feed_manager() -> MarketFeedManager:
    global _manager
    if _manager is None:
        _manager = MarketFeedManager()
    return _manager
