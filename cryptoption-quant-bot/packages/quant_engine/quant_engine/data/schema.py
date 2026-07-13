"""Normalized market-data schema shared by every provider.

One canonical shape so crypto (Binance), forex OTC, normal markets and
synthetic data all flow through the same validation and (later) feature code —
while staying clearly separated by `market_type`. Nothing here reaches the
network; providers do.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class MarketType(str, enum.Enum):
    CRYPTO_BINANCE = "CRYPTO_BINANCE"
    FOREX_OTC = "FOREX_OTC"
    NORMAL = "NORMAL"
    SYNTHETIC = "SYNTHETIC"


class ConnectionState(str, enum.Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    BACKFILLING = "BACKFILLING"
    ERROR = "ERROR"


# Canonical column order for candle frames (Polars/pandas).
CANDLE_COLUMNS: tuple[str, ...] = (
    "ts_utc", "asset", "market_type", "open", "high", "low", "close",
    "volume", "bid", "ask", "spread", "source", "is_otc", "session_id",
)


@dataclass(frozen=True, slots=True)
class NormalizedTick:
    ts_utc: datetime
    asset: str
    market_type: MarketType
    price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    source: str = ""
    is_otc: bool = False

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class NormalizedCandle:
    ts_utc: datetime          # bar OPEN time; bar covers [ts, ts + bar_seconds)
    asset: str
    market_type: MarketType
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    bid: float | None = None
    ask: float | None = None
    source: str = ""
    is_otc: bool = False
    session_id: str = ""
    quality_flags: dict[str, str] = field(default_factory=dict)

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def as_row(self) -> dict[str, object]:
        return {
            "ts_utc": self.ts_utc,
            "asset": self.asset,
            "market_type": self.market_type.value,
            "open": self.open, "high": self.high, "low": self.low, "close": self.close,
            "volume": self.volume, "bid": self.bid, "ask": self.ask,
            "spread": self.spread, "source": self.source,
            "is_otc": self.is_otc, "session_id": self.session_id,
        }


def session_id_for(ts: datetime) -> str:
    """UTC trading-day session id used for daily risk limits."""
    return ts.strftime("%Y-%m-%d")
