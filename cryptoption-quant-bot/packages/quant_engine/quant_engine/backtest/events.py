"""Typed events emitted by the event-driven backtester.

The simulator walks label samples in time order and emits a stream of these
events. They are the audit trail of a run and can be replayed/inspected.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PredictionEvent:
    ts: datetime
    asset: str
    p_up: float


@dataclass(frozen=True, slots=True)
class SignalEvent:
    ts: datetime
    asset: str
    action: str  # CALL | PUT | NO_TRADE


@dataclass(frozen=True, slots=True)
class RiskDecisionEvent:
    ts: datetime
    asset: str
    allowed: bool
    stake: float
    reason: str


@dataclass(frozen=True, slots=True)
class EntryAcceptedEvent:
    ts: datetime
    asset: str
    action: str
    stake: float
    payout: float
    entry_price: float


@dataclass(frozen=True, slots=True)
class EntryRejectedEvent:
    ts: datetime
    asset: str
    reason: str


@dataclass(frozen=True, slots=True)
class SettlementEvent:
    ts: datetime
    asset: str
    action: str
    outcome: str  # win | loss | tie
    stake: float
    payout: float
    pnl: float
    capital_after: float


@dataclass(frozen=True, slots=True)
class SessionHaltEvent:
    ts: datetime
    session: str
    reason: str


BacktestEvent = (
    PredictionEvent | SignalEvent | RiskDecisionEvent | EntryAcceptedEvent
    | EntryRejectedEvent | SettlementEvent | SessionHaltEvent
)
