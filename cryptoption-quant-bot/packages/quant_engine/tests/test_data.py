"""Tests for the data layer: providers, causal candle aggregation, validation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from quant_engine.data import (
    CandleAggregator,
    MarketType,
    NormalizedTick,
    SyntheticMarketDataProvider,
    validate_candles,
)
from quant_engine.data.candles import _floor_bar


# ---------- synthetic provider ----------

@pytest.mark.asyncio
async def test_synthetic_is_deterministic_by_seed():
    async def run() -> list[float]:
        p = SyntheticMarketDataProvider(seed=123, max_ticks=50)
        return [t.price async for t in p.stream_ticks()]

    a = await run()
    b = await run()
    assert a == b
    assert len(a) == 50


@pytest.mark.asyncio
async def test_synthetic_timestamps_increase_and_have_spread():
    p = SyntheticMarketDataProvider(seed=1, max_ticks=20, interval_seconds=1)
    ticks = [t async for t in p.stream_ticks()]
    for prev, nxt in zip(ticks, ticks[1:], strict=False):
        assert nxt.ts_utc > prev.ts_utc
    assert all(t.spread is not None and t.spread > 0 for t in ticks)
    assert all(t.market_type is MarketType.SYNTHETIC for t in ticks)


# ---------- causal candle aggregator ----------

def _tick(ts: datetime, price: float) -> NormalizedTick:
    return NormalizedTick(ts_utc=ts, asset="X", market_type=MarketType.SYNTHETIC,
                          price=price, volume=1.0)


def test_aggregator_emits_only_closed_bars():
    agg = CandleAggregator(bar_seconds=60)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    # three ticks in the first minute -> no closed bar yet
    assert agg.update(_tick(base, 100.0)) is None
    assert agg.update(_tick(base + timedelta(seconds=20), 101.0)) is None
    assert agg.update(_tick(base + timedelta(seconds=40), 99.0)) is None
    # a tick in the next minute closes the first bar
    closed = agg.update(_tick(base + timedelta(seconds=61), 100.5))
    assert closed is not None
    assert closed.open == 100.0 and closed.high == 101.0 and closed.low == 99.0
    assert closed.close == 99.0  # last price of the CLOSED minute, not the future tick
    assert closed.ts_utc == base


def test_aggregator_partial_is_never_the_future():
    agg = CandleAggregator(bar_seconds=60)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    agg.update(_tick(base, 100.0))
    partial = agg.current_partial()
    assert partial is not None and partial.close == 100.0


def test_floor_bar_aligns():
    ts = datetime(2024, 1, 1, 0, 1, 37, tzinfo=UTC)
    assert _floor_bar(ts, 60) == datetime(2024, 1, 1, 0, 1, 0, tzinfo=UTC)


# ---------- Polars validation ----------

def _frame(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(
        pl.col("ts_utc").cast(pl.Datetime(time_zone="UTC"))
    )


def _row(ts: datetime, o=1.0, h=1.1, low=0.9, c=1.0, asset="EURUSD_OTC", source="s"):
    return {"ts_utc": ts, "asset": asset, "open": o, "high": h, "low": low,
            "close": c, "volume": 1.0, "source": source}


def test_validation_clean_ok():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=i)) for i in range(10)]
    out, rep = validate_candles(_frame(rows), bar_seconds=60)
    assert rep.ok
    assert out.height == 10


def test_validation_removes_duplicates_and_bad_ohlc():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=i)) for i in range(5)]
    rows.append(_row(base + timedelta(minutes=2)))       # duplicate ts
    rows.append(_row(base + timedelta(minutes=5), h=0.5))  # high below body -> incoherent
    out, rep = validate_candles(_frame(rows), bar_seconds=60)
    codes = {i.code for i in rep.issues}
    assert "DUPLICATE_BAR" in codes
    assert "OHLC_INCOHERENT" in codes


def test_validation_reports_gaps_without_filling():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [_row(base + timedelta(minutes=i)) for i in range(5)]
    rows += [_row(base + timedelta(minutes=20 + i)) for i in range(5)]  # 15-bar hole
    out, rep = validate_candles(_frame(rows), bar_seconds=60)
    assert any(i.code == "GAP" for i in rep.issues)
    assert out.height == 10  # nothing was interpolated to fill the gap


def test_validation_flags_tz_naive():
    base = datetime(2024, 1, 1)
    df = pl.DataFrame([{"ts_utc": base, "asset": "X", "open": 1.0, "high": 1.0,
                        "low": 1.0, "close": 1.0, "volume": 1.0, "source": "s"}])
    _, rep = validate_candles(df, bar_seconds=60)
    assert not rep.ok
    assert any(i.code == "TZ_NAIVE" for i in rep.issues)
