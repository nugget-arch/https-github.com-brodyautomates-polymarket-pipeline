"""Abstract broker seam. LIVE EXECUTION IS DISABLED IN THIS PROJECT.

`BrokerAdapter` exists so that IF a broker ever publishes an official,
documented, ToS-compliant API, an adapter can be written against this
interface without touching research code. This repository intentionally
contains:

  * NO PocketOption connector of any kind,
  * NO reverse-engineered endpoints or WebSocket protocols,
  * NO browser automation, cookie/session capture, or fingerprinting,
  * NO credential storage.

Any attempt to place a live order raises `ExecutionDisabledError` because
`otc_lab.EXECUTION_ENABLED` is hard-coded False.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

import otc_lab


class ExecutionDisabledError(RuntimeError):
    """Raised on any attempt to execute a real order."""


@dataclass(frozen=True)
class OrderRequest:
    asset: str
    direction: str  # CALL | PUT
    stake: float
    expiry_seconds: int


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    order_id: str
    detail: str


class BrokerAdapter(abc.ABC):
    """Interface for a FUTURE official API. Implementations must be read-only
    (quotes/balance) unless `otc_lab.EXECUTION_ENABLED` is True — which it
    never is in this codebase."""

    @abc.abstractmethod
    def get_balance(self) -> float: ...

    @abc.abstractmethod
    def get_payout(self, asset: str, expiry_seconds: int) -> float: ...

    @abc.abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult: ...

    def _guard_execution(self) -> None:
        if not otc_lab.EXECUTION_ENABLED:
            raise ExecutionDisabledError(
                "Live execution is disabled by design in otc_lab. "
                "This platform is research/paper-trading only."
            )


class PaperBrokerAdapter(BrokerAdapter):
    """In-memory simulated broker for paper trading. Never touches a network."""

    def __init__(self, balance: float, payout: float):
        self._balance = balance
        self._payout = payout

    def get_balance(self) -> float:
        return self._balance

    def get_payout(self, asset: str, expiry_seconds: int) -> float:
        return self._payout

    def place_order(self, request: OrderRequest) -> OrderResult:
        # Paper fills are simulated by the replayer; the adapter only checks
        # stake vs balance. NOTE: even paper orders go through the guard-free
        # path because they move no real money.
        if request.stake > self._balance:
            return OrderResult(False, "", "insufficient balance")
        return OrderResult(True, f"paper-{id(request)}", "paper fill")

    def apply_pnl(self, pnl: float) -> None:
        self._balance += pnl
