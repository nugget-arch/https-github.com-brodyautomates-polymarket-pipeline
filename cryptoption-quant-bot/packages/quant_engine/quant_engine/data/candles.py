"""Causal candle aggregation from ticks.

A bar with open-time T covers [T, T + bar_seconds). The aggregator only EMITS
a bar once a tick belonging to a later bar arrives — i.e. only closed bars are
ever published, so no consumer can ever see a half-formed (future-peeking) bar.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .schema import NormalizedCandle, NormalizedTick, session_id_for


def _floor_bar(ts: datetime, bar_seconds: int) -> datetime:
    epoch = int(ts.replace(tzinfo=ts.tzinfo or UTC).timestamp())
    floored = epoch - (epoch % bar_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


class CandleAggregator:
    def __init__(self, bar_seconds: int = 60):
        self.bar_seconds = bar_seconds
        self._cur: NormalizedCandle | None = None
        self._cur_start: datetime | None = None

    def _new_bar(self, start: datetime, tick: NormalizedTick) -> NormalizedCandle:
        return NormalizedCandle(
            ts_utc=start, asset=tick.asset, market_type=tick.market_type,
            open=tick.price, high=tick.price, low=tick.price, close=tick.price,
            volume=tick.volume or 0.0, bid=tick.bid, ask=tick.ask,
            source=tick.source, is_otc=tick.is_otc, session_id=session_id_for(start),
        )

    def update(self, tick: NormalizedTick) -> NormalizedCandle | None:
        """Feed a tick. Returns a CLOSED candle when this tick rolls the bar
        over, otherwise None."""
        start = _floor_bar(tick.ts_utc, self.bar_seconds)
        if self._cur is None:
            self._cur = self._new_bar(start, tick)
            self._cur_start = start
            return None
        if start == self._cur_start:
            c = self._cur
            self._cur = NormalizedCandle(
                ts_utc=c.ts_utc, asset=c.asset, market_type=c.market_type,
                open=c.open, high=max(c.high, tick.price), low=min(c.low, tick.price),
                close=tick.price, volume=(c.volume + (tick.volume or 0.0)),
                bid=tick.bid, ask=tick.ask, source=c.source, is_otc=c.is_otc,
                session_id=c.session_id,
            )
            return None
        # tick belongs to a later bar -> current bar is now closed
        closed = self._cur
        self._cur = self._new_bar(start, tick)
        self._cur_start = start
        return closed

    def current_partial(self) -> NormalizedCandle | None:
        """The in-progress (NOT closed) bar. For live display only; never for
        features or labels."""
        return self._cur

    def expected_next_close(self) -> datetime | None:
        if self._cur_start is None:
            return None
        return self._cur_start + timedelta(seconds=self.bar_seconds)
