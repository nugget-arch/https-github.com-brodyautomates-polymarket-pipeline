"""Execution-mode broker adapters (API runtime).

All implement the quant_engine BrokerAdapter contract. None touches real money
or CryptOption. The Official adapter stays the disabled placeholder from
quant_engine.execution.

  * PaperBrokerAdapter      — virtual balance, simulated accept/reject + settle.
  * ShadowBrokerAdapter     — produces decisions, opens nothing, moves no balance;
                              records the hypothetical outcome for comparison.
  * ManualConfirmationBrokerAdapter — emits a signal and waits for a human to
                              confirm a trade THEY opened elsewhere; compares the
                              external result with the theoretical one. Never
                              sends an order anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass

from quant_engine.execution import BrokerAdapter, OrderRequest, OrderResult


@dataclass
class Settlement:
    outcome: str  # win | loss | tie
    pnl: float
    balance_after: float


class PaperBrokerAdapter(BrokerAdapter):  # type: ignore[misc]
    def __init__(self, balance: float, payout: float):
        self._balance = balance
        self._payout = payout

    def get_balance(self) -> float:
        return self._balance

    def get_payout(self, asset: str, expiry_seconds: int) -> float:
        return self._payout

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.stake <= 0 or request.stake > self._balance:
            return OrderResult(False, "", "insufficient_balance")
        return OrderResult(True, f"paper-{id(request)}", "accepted")

    def settle(self, direction_correct: bool | None, stake: float, payout: float) -> Settlement:
        if direction_correct is None:
            outcome, pnl = "tie", 0.0
        elif direction_correct:
            outcome, pnl = "win", stake * payout
        else:
            outcome, pnl = "loss", -stake
        self._balance += pnl
        return Settlement(outcome, round(pnl, 6), round(self._balance, 6))


class ShadowBrokerAdapter(BrokerAdapter):  # type: ignore[misc]
    """Decisions only. Balance never changes; nothing is opened."""

    def __init__(self, payout: float):
        self._payout = payout

    def get_balance(self) -> float:
        return 0.0

    def get_payout(self, asset: str, expiry_seconds: int) -> float:
        return self._payout

    def place_order(self, request: OrderRequest) -> OrderResult:
        # Shadow never opens a position; it records the intent only.
        return OrderResult(False, "", "shadow_no_execution")

    def hypothetical(self, direction_correct: bool | None, stake: float,
                     payout: float) -> Settlement:
        if direction_correct is None:
            return Settlement("tie", 0.0, 0.0)
        pnl = stake * payout if direction_correct else -stake
        return Settlement("win" if direction_correct else "loss", round(pnl, 6), 0.0)


@dataclass
class ManualPending:
    signal_id: int
    asset: str
    action: str
    stake: float
    theoretical: str = ""


class ManualConfirmationBrokerAdapter(BrokerAdapter):  # type: ignore[misc]
    """Emits signals; a human confirms trades opened elsewhere. No orders sent."""

    def __init__(self, payout: float):
        self._payout = payout
        self.pending: dict[int, ManualPending] = {}

    def get_balance(self) -> float:
        return 0.0

    def get_payout(self, asset: str, expiry_seconds: int) -> float:
        return self._payout

    def place_order(self, request: OrderRequest) -> OrderResult:
        # Manual mode does not place orders; it registers a pending confirmation.
        return OrderResult(False, "", "awaiting_manual_confirmation")

    @staticmethod
    def compare(external_result: str, theoretical_result: str) -> bool:
        """True when the human-reported outcome matches the model's theory."""
        return external_result.upper() == theoretical_result.upper()
