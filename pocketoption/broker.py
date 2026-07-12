"""
Broker interface.

`PaperBroker` simulates fills against live candle data so you can run the bot
end-to-end with zero money at risk. `PocketOptionBroker` is a documented stub:
PocketOption has no official API, so a real integration relies on an unofficial
library (e.g. the community `pocketoptionapi` packages) or browser automation,
both of which may violate PocketOption's terms and break without notice. It is
intentionally left unimplemented so nobody wires real money to untested code by
accident — fill it in yourself, consciously, if you choose to.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    direction: str  # CALL | PUT
    stake: float
    entry_price: float
    opened_at: float
    expiry_seconds: int


@dataclass
class TradeOutcome:
    won: bool
    tie: bool
    entry_price: float
    exit_price: float
    payout: float


class BrokerBase:
    def get_balance(self) -> float:
        raise NotImplementedError

    def latest_price(self, symbol: str) -> float:
        raise NotImplementedError

    def place(self, symbol: str, direction: str, stake: float, expiry_seconds: int) -> Position:
        raise NotImplementedError

    def settle(self, pos: Position) -> TradeOutcome:
        raise NotImplementedError


class PaperBroker(BrokerBase):
    """
    Paper broker. You feed it a price source callable `price_fn(symbol)->float`
    (e.g. pulling the last close from `data.fetch_candles`). Settlement compares
    the price now vs. at entry.
    """

    def __init__(self, price_fn, balance: float = 1000.0, payout: float = 0.85):
        self._price_fn = price_fn
        self._balance = balance
        self._payout = payout
        self.history: list[TradeOutcome] = []

    def get_balance(self) -> float:
        return self._balance

    def latest_price(self, symbol: str) -> float:
        return float(self._price_fn(symbol))

    def place(self, symbol: str, direction: str, stake: float, expiry_seconds: int) -> Position:
        return Position(
            symbol=symbol,
            direction=direction,
            stake=stake,
            entry_price=self.latest_price(symbol),
            opened_at=time.time(),
            expiry_seconds=expiry_seconds,
        )

    def settle(self, pos: Position) -> TradeOutcome:
        exit_price = self.latest_price(pos.symbol)
        if exit_price == pos.entry_price:
            outcome = TradeOutcome(False, True, pos.entry_price, exit_price, self._payout)
        else:
            up = exit_price > pos.entry_price
            won = (pos.direction == "CALL" and up) or (pos.direction == "PUT" and not up)
            self._balance += pos.stake * self._payout if won else -pos.stake
            outcome = TradeOutcome(won, False, pos.entry_price, exit_price, self._payout)
        self.history.append(outcome)
        return outcome


class PocketOptionBroker(BrokerBase):
    """Unimplemented on purpose. See module docstring."""

    def __init__(self, ssid: str = "", demo: bool = True):
        self.ssid = ssid
        self.demo = demo

    def _not_implemented(self):
        raise NotImplementedError(
            "Live PocketOption trading requires an unofficial API/browser "
            "automation that may violate PocketOption's terms and is not shipped "
            "here. Implement this class against a library you trust, keep demo=True "
            "until you have validated it, and never risk money you can't lose."
        )

    def get_balance(self) -> float:
        self._not_implemented()

    def latest_price(self, symbol: str) -> float:
        self._not_implemented()

    def place(self, symbol: str, direction: str, stake: float, expiry_seconds: int) -> Position:
        self._not_implemented()

    def settle(self, pos: Position) -> TradeOutcome:
        self._not_implemented()
