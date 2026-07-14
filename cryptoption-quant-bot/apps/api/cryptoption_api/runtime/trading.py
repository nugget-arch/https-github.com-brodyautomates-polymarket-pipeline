"""TradingRuntime core — deterministic, synchronous, testable.

Feed closed candles in with `on_closed_candle`; it returns a list of typed
RuntimeEvents (signal / decision / order_opened / settlement / balance / halt).
An async session driver persists them, journals them (hash chain) and publishes
them over WebSocket. Keeping the core sync + pure makes the trading logic unit
testable without a database or event loop.

Modes:
  * PAPER  — simulated fills + balance via PaperBrokerAdapter + RiskManager.
  * SHADOW — decisions + hypothetical outcomes; no fills, no balance.
  * MANUAL — emits a signal and stops; a human confirms externally (handled by
             the REST manual flow, not this loop).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quant_engine.backtest.engine import break_even_win_rate
from quant_engine.config import RiskConfig
from quant_engine.execution import OrderRequest
from quant_engine.features import build_features, feature_columns
from quant_engine.risk import RiskManager

from .brokers import PaperBrokerAdapter, ShadowBrokerAdapter

PredictFn = Callable[[pd.DataFrame], float]


@dataclass
class RuntimeEvent:
    type: str
    payload: dict[str, Any]


@dataclass
class _OpenPosition:
    action: str
    stake: float
    payout: float
    entry_price: float
    expiry_candle: int  # closed-candle counter at which it settles


@dataclass
class TradingRuntime:
    mode: str
    predict_fn: PredictFn
    threshold: float
    payout: float
    expiry_bars: int = 1
    warmup: int = 80
    risk_cfg: RiskConfig = field(default_factory=RiskConfig)

    def __post_init__(self) -> None:
        self._buffer: list[dict[str, Any]] = []
        self._n_closed = 0
        self._open: _OpenPosition | None = None
        self._risk = RiskManager(self.risk_cfg)
        self._paper = PaperBrokerAdapter(self.risk_cfg.initial_capital, self.payout)
        self._shadow = ShadowBrokerAdapter(self.payout)
        self.n_signals = 0
        self.n_trades = 0
        self.n_wins = 0

    @property
    def break_even(self) -> float:
        return float(break_even_win_rate(self.payout))

    @property
    def balance(self) -> float:
        return self._paper.get_balance()

    def kill(self) -> None:
        self._risk.kill()

    def on_closed_candle(self, candle: dict[str, Any]) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        self._buffer.append(candle)
        idx = self._n_closed
        self._n_closed += 1

        # settle a matured position first
        if self._open is not None and idx >= self._open.expiry_candle:
            events += self._settle(candle)

        if len(self._buffer) < self.warmup:
            return events

        feats = build_features(pd.DataFrame(self._buffer))
        fcols = feature_columns(feats)
        row = feats.iloc[[-1]][fcols]
        if row.isna().any(axis=1).item():
            return events
        p_up = float(self.predict_fn(row))

        action = (
            "CALL"
            if p_up >= self.threshold
            else "PUT"
            if p_up <= 1 - self.threshold
            else "NO_TRADE"
        )
        events.append(
            RuntimeEvent(
                "signal",
                {
                    "ts_utc": candle["ts_utc"],
                    "p_up": round(p_up, 4),
                    "action": action,
                    "threshold_call": round(self.threshold, 4),
                    "threshold_put": round(1 - self.threshold, 4),
                },
            )
        )
        if action == "NO_TRADE":
            return events
        self.n_signals += 1

        if self._open is not None:
            events.append(
                RuntimeEvent("decision", {"action": "skip", "reason": "ACTIVE_POSITION_EXISTS"})
            )
            return events

        session_id = str(candle.get("session_id", ""))
        decision = self._risk.pre_trade(session_id, idx)
        if not decision.allowed:
            events.append(
                RuntimeEvent("decision", {"action": "blocked", "reason": decision.reason})
            )
            return events

        if self.mode == "MANUAL":
            # emit a proposal; the human confirms via REST. No loop execution.
            events.append(
                RuntimeEvent(
                    "manual_proposal",
                    {
                        "action": action,
                        "stake": decision.stake,
                        "payout": self.payout,
                        "entry_price_hint": candle["close"],
                    },
                )
            )
            return events

        stake = decision.stake
        broker = self._paper if self.mode == "PAPER" else self._shadow
        order = broker.place_order(
            OrderRequest(str(candle["asset"]), action, stake, self.expiry_bars * 60)
        )
        self._open = _OpenPosition(
            action=action,
            stake=stake,
            payout=self.payout,
            entry_price=float(candle["close"]),
            expiry_candle=idx + self.expiry_bars,
        )
        events.append(
            RuntimeEvent(
                "order_opened",
                {
                    "mode": self.mode,
                    "action": action,
                    "stake": stake,
                    "payout": self.payout,
                    "entry_price": self._open.entry_price,
                    "accepted": order.accepted,
                },
            )
        )
        return events

    def _settle(self, candle: dict[str, Any]) -> list[RuntimeEvent]:
        assert self._open is not None
        pos = self._open
        exit_price = float(candle["close"])
        if exit_price == pos.entry_price:
            correct: bool | None = None
        else:
            up = exit_price > pos.entry_price
            correct = (pos.action == "CALL") == up

        if self.mode == "PAPER":
            s = self._paper.settle(correct, pos.stake, pos.payout)
            self._risk.settle(pos.stake, s.pnl)
        else:  # SHADOW
            s = self._shadow.hypothetical(correct, pos.stake, pos.payout)

        if s.outcome != "tie":
            self.n_trades += 1
            self.n_wins += int(s.outcome == "win")
        self._open = None
        evs = [
            RuntimeEvent(
                "settlement",
                {
                    "outcome": s.outcome,
                    "pnl": s.pnl,
                    "exit_price": exit_price,
                    "balance": self.balance if self.mode == "PAPER" else None,
                },
            )
        ]
        if self.mode == "PAPER":
            evs.append(RuntimeEvent("balance", {"balance": round(self.balance, 2)}))
        return evs
