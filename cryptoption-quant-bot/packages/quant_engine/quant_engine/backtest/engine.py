"""Event-driven binary-options backtester.

Model of a "higher/lower" trade:
  * signal at close of bar t; enter at OPEN of bar t+latency (baked into labels);
  * expire `expiry_bars` later; win if price moved the predicted way;
  * win pays stake*payout, loss costs stake, exact tie per policy;
  * variable payout U(base±jitter) floored; broker rejections; optional slippage;
  * at most ONE open trade per asset.

PnL uses the trade's ACTUAL payout — never a traditional percentage return. The
decision threshold comes from the payout FLOOR + safety margin (+ optional
validation CI half-width); never from the test set.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import BacktestConfig, RiskConfig
from ..risk.manager import RiskManager
from .events import (
    BacktestEvent,
    EntryAcceptedEvent,
    EntryRejectedEvent,
    PredictionEvent,
    RiskDecisionEvent,
    SettlementEvent,
    SignalEvent,
)


def break_even_win_rate(payout: float) -> float:
    return 1.0 / (1.0 + payout)


def decision_threshold(cfg: BacktestConfig, val_ci_halfwidth: float | None = None) -> float:
    be = break_even_win_rate(cfg.payout_floor)
    margin = cfg.threshold_margin
    if cfg.threshold_use_val_ci and val_ci_halfwidth is not None:
        margin = max(margin, val_ci_halfwidth)
    return min(0.99, be + margin)


@dataclass
class BacktestResult:
    trade_log: pd.DataFrame
    events: list[BacktestEvent] = field(default_factory=list)
    ending_capital: float = 0.0
    starting_capital: float = 0.0


class BinaryBacktestEngine:
    def __init__(self, bt_cfg: BacktestConfig, risk_cfg: RiskConfig, seed: int = 7):
        self.cfg = bt_cfg
        self.risk_cfg = risk_cfg
        self.seed = seed

    def run(
        self, samples: pd.DataFrame, p_up: np.ndarray, threshold: float,
        collect_events: bool = False,
    ) -> BacktestResult:
        assert len(samples) == len(p_up)
        rng = np.random.default_rng(self.seed)
        risk = RiskManager(self.risk_cfg)

        order = np.argsort(samples["ts_utc"].to_numpy(), kind="stable")
        samples = samples.iloc[order].reset_index(drop=True)
        p_up = np.asarray(p_up)[order]

        open_until: dict[str, int] = {}
        records: list[dict] = []
        events: list[BacktestEvent] = []

        def emit(ev: BacktestEvent) -> None:
            if collect_events:
                events.append(ev)

        for i in range(len(samples)):
            row = samples.iloc[i]
            prob = float(p_up[i])
            ts, asset = row["ts_utc"], str(row["asset"])
            emit(PredictionEvent(ts, asset, prob))

            if prob >= threshold:
                action = "CALL"
            elif prob <= 1.0 - threshold:
                action = "PUT"
            else:
                emit(SignalEvent(ts, asset, "NO_TRADE"))
                continue
            emit(SignalEvent(ts, asset, action))

            if asset in open_until and int(row["signal_idx"]) <= open_until[asset]:
                continue  # one open trade per asset

            decision = risk.pre_trade(str(row["session_id"]), int(row["signal_idx"]))
            emit(RiskDecisionEvent(ts, asset, decision.allowed, decision.stake, decision.reason))
            if not decision.allowed:
                records.append(self._blocked(row, action, prob, decision.reason, risk.capital))
                continue

            if rng.uniform() < self.cfg.rejection_prob:
                emit(EntryRejectedEvent(ts, asset, "broker_rejected"))
                records.append(self._blocked(row, action, prob, "rejected", risk.capital))
                continue

            payout = float(np.clip(
                rng.uniform(self.cfg.payout_base - self.cfg.payout_jitter,
                            self.cfg.payout_base + self.cfg.payout_jitter),
                self.cfg.payout_floor, 0.99))
            stake = decision.stake
            entry = float(row["entry_price"])
            emit(EntryAcceptedEvent(ts, asset, action, stake, payout, entry))

            if bool(row["is_tie"]):
                if self.cfg.tie_policy == "TIE":
                    outcome, pnl = "tie", 0.0
                elif self.cfg.tie_policy == "LOSS":
                    outcome, pnl = "loss", -stake
                else:  # EXCLUDE ties shouldn't reach here, but be safe
                    continue
            else:
                won = (action == "CALL") == bool(row["y_up"])
                outcome = "win" if won else "loss"
                pnl = stake * payout if won else -stake

            risk.settle(stake, pnl)
            open_until[asset] = int(row["horizon_end"])
            records.append({
                "ts_utc": ts, "asset": asset, "session_id": str(row["session_id"]),
                "action": action, "p_up": prob, "stake": stake, "payout": payout,
                "entry_price": entry, "expiry_price": float(row["expiry_price"]),
                "outcome": outcome, "pnl": round(pnl, 6),
                "capital_after": round(risk.capital, 6),
                "regime": str(row.get("regime", "all")),
            })
            emit(SettlementEvent(ts, asset, action, outcome, stake, payout,
                                 round(pnl, 6), round(risk.capital, 6)))

        return BacktestResult(
            trade_log=pd.DataFrame(records), events=events,
            ending_capital=round(risk.capital, 6),
            starting_capital=self.risk_cfg.initial_capital,
        )

    @staticmethod
    def _blocked(row: pd.Series, action: str, prob: float, reason: str,
                 capital: float) -> dict:
        return {
            "ts_utc": row["ts_utc"], "asset": str(row["asset"]),
            "session_id": str(row["session_id"]), "action": action, "p_up": prob,
            "stake": 0.0, "payout": 0.0, "entry_price": float(row["entry_price"]),
            "expiry_price": float(row["expiry_price"]),
            "outcome": f"blocked:{reason}" if reason not in ("rejected",) else "rejected",
            "pnl": 0.0, "capital_after": round(capital, 6),
            "regime": str(row.get("regime", "all")),
        }
