"""Execution seam. REAL-MONEY EXECUTION IS DISABLED IN THIS PROJECT.

`BrokerAdapter` is the abstract interface. The only official-provider
implementation, `OfficialCryptOptionBrokerAdapter`, is a hard placeholder: every
execution method raises `OfficialApiUnavailableError`. It contains NO URLs, no
endpoints, no tokens, no cookies, no private headers, and no protocols obtained
by inspection. It may only be implemented once the provider delivers official
documentation, official auth, a demo environment, written permission for bots,
and documented endpoints (balance, assets, payout, order creation, results,
rate limits, official WebSocket).

The Paper/Shadow/Manual adapters live in the API runtime (they need app state);
this module fixes the contract and the safety error now.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

from . import EXECUTION_ENABLED


class OfficialApiUnavailableError(RuntimeError):
    """Raised by the official adapter placeholder. It has no implementation."""


class ExecutionDisabledError(RuntimeError):
    """Raised if anything attempts real execution while EXECUTION_ENABLED is False."""


@dataclass(frozen=True)
class OrderRequest:
    asset: str
    action: str  # CALL | PUT
    stake: float
    expiry_seconds: int


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    external_id: str
    detail: str


class BrokerAdapter(abc.ABC):
    """Abstract broker. Real implementations must call `_guard_execution()`
    before any order placement; it refuses while execution is disabled."""

    @abc.abstractmethod
    def get_balance(self) -> float: ...

    @abc.abstractmethod
    def get_payout(self, asset: str, expiry_seconds: int) -> float: ...

    @abc.abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult: ...

    def _guard_execution(self) -> None:
        if not EXECUTION_ENABLED:
            raise ExecutionDisabledError(
                "Real-money execution is disabled by design in cryptoption-quant-bot."
            )


class OfficialCryptOptionBrokerAdapter(BrokerAdapter):
    """Disabled placeholder. Do NOT add URLs/endpoints/tokens/cookies here."""

    def _unavailable(self) -> None:
        raise OfficialApiUnavailableError(
            "No official, documented, authorized CryptOption API is integrated. "
            "This adapter is a placeholder and performs no network activity."
        )

    def get_balance(self) -> float:
        self._unavailable()
        raise AssertionError  # unreachable

    def get_payout(self, asset: str, expiry_seconds: int) -> float:
        self._unavailable()
        raise AssertionError  # unreachable

    def place_order(self, request: OrderRequest) -> OrderResult:
        self._unavailable()
        raise AssertionError  # unreachable
