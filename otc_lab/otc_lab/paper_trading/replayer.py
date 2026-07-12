"""Historical market replayer with a simulated clock.

Feeds bars one at a time in chronological order. At each bar close the
strategy sees ONLY history up to that bar, produces P(up), and the decision
(trade in paper mode / record-only in shadow mode) is journaled immutably.
Settlement occurs when the simulated clock reaches the expiry bar.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..broker.adapter import OrderRequest, PaperBrokerAdapter
from ..backtest.engine import decision_threshold
from ..config import ExperimentConfig, break_even_win_rate
from ..features.engine import build_features, feature_columns
from ..logging_setup import get_logger
from ..risk.manager import RiskManager
from .journal import Journal

log = get_logger("paper")


class SimClock:
    """Simulated clock: advances bar by bar; optional wall-clock pacing."""

    def __init__(self, speed: float = 0.0):
        self.speed = speed
        self.now: pd.Timestamp | None = None

    def advance(self, ts: pd.Timestamp) -> None:
        self.now = ts
        if self.speed > 0:
            time.sleep(self.speed)


@dataclass
class _OpenTrade:
    direction: str
    stake: float
    payout: float
    entry_price: float
    expiry_pos: int


class MarketReplayer:
    """Replay one asset's candles through a fitted strategy.

    mode="shadow": signals + hypothetical decisions journaled, no fills.
    mode="paper":  fills simulated via PaperBrokerAdapter + RiskManager.
    """

    def __init__(self, cfg: ExperimentConfig, strategy, journal: Journal | None = None):
        self.cfg = cfg
        self.strategy = strategy
        self.journal = journal or Journal(cfg.paper.journal_path)
        self.clock = SimClock(cfg.paper.speed)

    def run(self, candles: pd.DataFrame, expiry_bars: int, warmup_bars: int = 100) -> dict:
        cfg = self.cfg
        mode = cfg.paper.mode
        lat = cfg.labels.latency_bars
        threshold = decision_threshold(cfg.backtest)
        risk = RiskManager(cfg.risk)
        broker = PaperBrokerAdapter(cfg.risk.initial_capital, cfg.backtest.payout_base)
        rng = np.random.default_rng(cfg.seed)

        candles = candles.sort_values("timestamp").reset_index(drop=True)
        feats_full = build_features(candles, cfg.features)
        fcols = feature_columns(feats_full)

        open_trade: _OpenTrade | None = None
        n_signals = n_trades = n_wins = 0

        self.journal.append("session_start", {
            "mode": mode, "asset": str(candles["asset"].iloc[0]),
            "expiry_bars": expiry_bars, "threshold": threshold,
            "break_even": break_even_win_rate(cfg.backtest.payout_floor),
            "strategy": getattr(self.strategy, "name", "?"),
        })

        for pos in range(warmup_bars, len(candles) - lat - expiry_bars):
            bar_ts = candles["timestamp"].iloc[pos]
            self.clock.advance(bar_ts)

            # settle a matured trade first
            if open_trade is not None and pos >= open_trade.expiry_pos:
                expiry_price = float(candles["close"].iloc[open_trade.expiry_pos])
                if expiry_price == open_trade.entry_price:
                    outcome, pnl = "tie", 0.0
                else:
                    won = (open_trade.direction == "CALL") == (expiry_price > open_trade.entry_price)
                    outcome = "win" if won else "loss"
                    pnl = open_trade.stake * open_trade.payout if won else -open_trade.stake
                    n_trades += 1
                    n_wins += int(won)
                if mode == "paper":
                    risk.settle(open_trade.stake, pnl)
                    broker.apply_pnl(pnl)
                self.journal.append("settlement", {
                    "outcome": outcome, "pnl": round(pnl, 6),
                    "capital": round(risk.capital, 2),
                })
                open_trade = None

            # NOTE: features computed on full frame are causal (backward-looking
            # only), so reading row `pos` equals recomputing on candles[:pos+1].
            x_row = feats_full.iloc[[pos]][fcols]
            if x_row.isna().any(axis=1).item():
                continue
            p_up = float(self.strategy.predict_proba_up(x_row)[0])

            direction = "CALL" if p_up >= threshold else ("PUT" if p_up <= 1 - threshold else None)
            self.journal.append("signal", {
                "bar_ts": bar_ts, "p_up": round(p_up, 4),
                "direction": direction or "NONE",
            })
            if direction is None:
                continue
            n_signals += 1

            if open_trade is not None:
                self.journal.append("decision", {"action": "skip", "reason": "trade_open"})
                continue

            if mode == "shadow":
                self.journal.append("decision", {"action": "shadow_only", "direction": direction})
                # track hypothetical outcome for stats
                entry_pos = pos + lat
                open_trade = _OpenTrade(direction, 0.0, cfg.backtest.payout_base,
                                        float(candles["open"].iloc[entry_pos]),
                                        entry_pos + expiry_bars - 1)
                continue

            decision = risk.pre_trade(str(candles["session"].iloc[pos]), pos)
            if not decision.allowed:
                self.journal.append("decision", {"action": "blocked", "reason": decision.reason})
                continue
            payout = float(np.clip(
                rng.uniform(cfg.backtest.payout_base - cfg.backtest.payout_jitter,
                            cfg.backtest.payout_base + cfg.backtest.payout_jitter),
                cfg.backtest.payout_floor, 0.99))
            order = broker.place_order(OrderRequest(
                asset=str(candles["asset"].iloc[pos]), direction=direction,
                stake=decision.stake,
                expiry_seconds=expiry_bars * cfg.data.bar_seconds))
            if not order.accepted:
                self.journal.append("decision", {"action": "rejected", "reason": order.detail})
                continue
            entry_pos = pos + lat
            open_trade = _OpenTrade(direction, decision.stake, payout,
                                    float(candles["open"].iloc[entry_pos]),
                                    entry_pos + expiry_bars - 1)
            self.journal.append("decision", {
                "action": "paper_fill", "direction": direction,
                "stake": decision.stake, "payout": payout,
            })

        summary = {
            "mode": mode, "signals": n_signals, "settled_trades": n_trades,
            "wins": n_wins,
            "win_rate": (n_wins / n_trades) if n_trades else None,
            "final_capital": round(risk.capital, 2) if mode == "paper" else None,
            "journal_ok": self.journal.verify(),
        }
        self.journal.append("session_end", summary)
        log.info("replay done", extra={"ctx_summary": summary})
        return summary
