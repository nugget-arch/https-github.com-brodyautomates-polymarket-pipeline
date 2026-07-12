"""Event-driven binary-options backtest.

Processes label samples in strict time order. Realism knobs:
  * variable payout per trade: U(base - jitter, base + jitter), seeded;
  * entry rejections with probability `rejection_prob` (broker refuses);
  * latency already baked into the labels (entry = open of t + latency);
  * missing data: samples that would bridge a gap were never emitted;
  * at most ONE simultaneous open trade per asset;
  * PnL uses the actual payout of the trade: win = +stake*payout, loss = -stake,
    tie handled per label config (refund/loss/drop).

The DECISION threshold is computed from the *floor* payout (conservative), a
config safety margin, and optionally the validation-fold CI half-width — never
from the test set.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import BacktestConfig, RiskConfig, break_even_win_rate
from ..logging_setup import get_logger
from ..risk.manager import RiskManager

log = get_logger("backtest")


@dataclass
class TradeRecord:
    timestamp: object
    asset: str
    session: str
    direction: str        # CALL | PUT
    p_up: float
    stake: float
    payout: float
    entry_price: float
    expiry_price: float
    outcome: str          # win | loss | tie | rejected | blocked
    pnl: float
    capital_after: float
    regime: str = "all"   # causal volatility regime label, if provided


def decision_threshold(
    cfg: BacktestConfig, val_ci_halfwidth: float | None = None
) -> float:
    """P(up) needed to CALL (PUT is symmetric at 1 - threshold).

    threshold = break_even(payout_floor) + margin [+ validation CI half-width]
    Uses the payout FLOOR so a payout worse than average still clears.
    """
    be = break_even_win_rate(cfg.payout_floor)
    margin = cfg.threshold_margin
    if cfg.threshold_use_val_ci and val_ci_halfwidth is not None:
        margin = max(margin, val_ci_halfwidth)
    return min(0.99, be + margin)


class BinaryBacktestEngine:
    def __init__(
        self,
        bt_cfg: BacktestConfig,
        risk_cfg: RiskConfig,
        seed: int = 7,
        tie_policy: str = "refund",
    ):
        self.cfg = bt_cfg
        self.risk_cfg = risk_cfg
        self.seed = seed
        self.tie_policy = tie_policy

    def run(
        self,
        samples: pd.DataFrame,
        p_up: np.ndarray,
        threshold: float,
    ) -> pd.DataFrame:
        """samples: label frame rows (any subset), must include timestamp, asset,
        session, entry_idx, horizon_end, entry_price, expiry_price, y_up, is_tie.
        p_up aligned to samples. Returns a trade log DataFrame (all events)."""
        assert len(samples) == len(p_up)
        rng = np.random.default_rng(self.seed)
        risk = RiskManager(self.risk_cfg)

        order = np.argsort(samples["timestamp"].to_numpy(), kind="stable")
        samples = samples.iloc[order].reset_index(drop=True)
        p_up = np.asarray(p_up)[order]

        open_until: dict[str, int] = {}  # asset -> horizon_end of open trade
        records: list[TradeRecord] = []

        for i in range(len(samples)):
            row = samples.iloc[i]
            prob = float(p_up[i])

            if prob >= threshold:
                direction = "CALL"
            elif prob <= 1.0 - threshold:
                direction = "PUT"
            else:
                continue  # no edge estimate beyond safety margin -> no trade

            asset = row["asset"]
            # one simultaneous trade per asset
            if asset in open_until and row["signal_idx"] <= open_until[asset]:
                continue

            decision = risk.pre_trade(str(row["session"]), int(row["signal_idx"]))
            if not decision.allowed:
                records.append(TradeRecord(
                    row["timestamp"], asset, str(row["session"]), direction, prob,
                    0.0, 0.0, float(row["entry_price"]), float(row["expiry_price"]),
                    "blocked:" + decision.reason, 0.0, risk.capital,
                    str(row.get("regime", "all")),
                ))
                continue

            # broker-side rejection
            if rng.uniform() < self.cfg.rejection_prob:
                records.append(TradeRecord(
                    row["timestamp"], asset, str(row["session"]), direction, prob,
                    0.0, 0.0, float(row["entry_price"]), float(row["expiry_price"]),
                    "rejected", 0.0, risk.capital,
                    str(row.get("regime", "all")),
                ))
                continue

            payout = float(np.clip(
                rng.uniform(self.cfg.payout_base - self.cfg.payout_jitter,
                            self.cfg.payout_base + self.cfg.payout_jitter),
                self.cfg.payout_floor, 0.99,
            ))
            stake = decision.stake

            if bool(row["is_tie"]):
                if self.tie_policy == "refund":
                    outcome, pnl = "tie", 0.0
                else:  # "loss" (ties as losses — worst-case assumption)
                    outcome, pnl = "loss", -stake
            else:
                won = (direction == "CALL") == bool(row["y_up"])
                outcome = "win" if won else "loss"
                pnl = stake * payout if won else -stake

            risk.settle(stake, pnl)
            open_until[asset] = int(row["horizon_end"])
            records.append(TradeRecord(
                row["timestamp"], asset, str(row["session"]), direction, prob,
                stake, payout, float(row["entry_price"]), float(row["expiry_price"]),
                outcome, round(pnl, 6), round(risk.capital, 6),
                str(row.get("regime", "all")),
            ))

        return pd.DataFrame([r.__dict__ for r in records])
