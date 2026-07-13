"""In-process async pub/sub event bus.

Phase 2 uses an in-memory broadcaster (simple, deterministic, testable). The
interface is intentionally Redis-shaped (publish/subscribe on a channel) so a
`RedisEventBus` can replace it later without touching callers.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self, max_queue: int = 1000):
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._max_queue = max_queue

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subs.get(channel, ())):
            if q.qsize() >= self._max_queue:
                # Drop the oldest to bound memory; the client will detect the
                # gap via sequence IDs and recover state over REST.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subs[channel].add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[channel].discard(q)

    def subscriber_count(self, channel: str) -> int:
        return len(self._subs.get(channel, ()))


# Singleton bus for the app process.
_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
