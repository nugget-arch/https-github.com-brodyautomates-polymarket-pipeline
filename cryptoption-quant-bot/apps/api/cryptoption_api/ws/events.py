"""WebSocket event envelope + typed event names.

Every server->client message is `{seq, ts, type, payload}`. `seq` is a
per-connection monotonic counter so the client can detect gaps/duplicates and
recover missed state via REST. Payloads are Pydantic models (schema-validated
before send).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

WsEventType = Literal[
    "connection.status",
    "market.tick",
    "market.candle",
    "heartbeat",
    "data_quality.alert",
    "error",
]


class WsEnvelope(BaseModel):
    seq: int
    ts: str
    type: WsEventType
    payload: dict[str, Any]

    @classmethod
    def make(cls, seq: int, type_: WsEventType, payload: dict[str, Any]) -> WsEnvelope:
        return cls(seq=seq, ts=datetime.now(UTC).isoformat(), type=type_, payload=payload)


class MarketTickPayload(BaseModel):
    asset: str
    market_type: str
    ts_utc: str
    price: float
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None


class MarketCandlePayload(BaseModel):
    asset: str
    market_type: str
    ts_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool


class ConnectionStatusPayload(BaseModel):
    state: str
    asset: str | None = None
    detail: str = ""
