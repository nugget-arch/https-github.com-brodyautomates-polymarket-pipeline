"""PaperBroker — simulated broker with a virtual balance and an append-only
ledger. Used for deterministic paper trading. It moves NO real money and has no
network access. Sizing goes through the RiskManager, so the anti-martingale
guarantee holds here too (a loss never increases the next stake).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PaperFill:
    ts: datetime
    asset: str
    action: str
    stake: float
    payout: float
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PaperSettlement:
    ts: datetime
    asset: str
    outcome: str  # win | loss | tie
    pnl: float
    balance_after: float


class PaperBroker:
    def __init__(self, balance: float = 10_000.0):
        self._balance = balance
        self.fills: list[PaperFill] = []
        self.settlements: list[PaperSettlement] = []

    @property
    def balance(self) -> float:
        return self._balance

    def place(self, ts: datetime, asset: str, action: str, stake: float,
              payout: float) -> PaperFill:
        if stake <= 0 or stake > self._balance:
            fill = PaperFill(ts, asset, action, stake, payout, False, "insufficient_balance")
        else:
            fill = PaperFill(ts, asset, action, stake, payout, True, "accepted")
        self.fills.append(fill)
        return fill

    def settle(self, ts: datetime, asset: str, outcome: str, stake: float,
               payout: float) -> PaperSettlement:
        if outcome == "win":
            pnl = stake * payout
        elif outcome == "loss":
            pnl = -stake
        else:  # tie -> stake refunded
            pnl = 0.0
        self._balance += pnl
        s = PaperSettlement(ts, asset, outcome, round(pnl, 6), round(self._balance, 6))
        self.settlements.append(s)
        return s


@dataclass
class PaperLedger:
    entries: list[dict] = field(default_factory=list)

    def record(self, kind: str, payload: dict) -> None:
        self.entries.append({"kind": kind, **payload})
