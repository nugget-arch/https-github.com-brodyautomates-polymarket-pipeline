"""Monte Carlo risk-of-ruin simulation.

Resamples the empirical settled-trade PnL-per-unit-stake distribution into
many alternative orderings/paths, applies the same fixed-fraction sizing, and
reports the probability of hitting a ruin threshold. This answers "even if the
edge were real, how often would this bankroll die anyway?".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RuinReport:
    n_paths: int
    horizon_trades: int
    ruin_threshold: float      # e.g. 0.5 => capital halves
    prob_ruin: float
    median_final_equity: float
    p5_final_equity: float
    p95_final_equity: float


def ruin_probability(
    trade_log: pd.DataFrame,
    initial_capital: float,
    risk_fraction: float,
    n_paths: int = 5000,
    horizon_trades: int = 1000,
    ruin_threshold: float = 0.5,
    seed: int = 7,
) -> RuinReport:
    settled = trade_log[trade_log["outcome"].isin(["win", "loss"])]
    if settled.empty:
        return RuinReport(n_paths, horizon_trades, ruin_threshold,
                          float("nan"), float("nan"), float("nan"), float("nan"))

    # PnL per unit of stake: +payout on win, -1 on loss
    unit = np.where(
        settled["outcome"].to_numpy() == "win",
        settled["payout"].to_numpy(),
        -1.0,
    )
    rng = np.random.default_rng(seed)
    draws = rng.choice(unit, size=(n_paths, horizon_trades), replace=True)

    # fixed-fraction compounding: equity *= (1 + f * unit_pnl)
    growth = 1.0 + risk_fraction * draws
    equity_paths = initial_capital * np.cumprod(growth, axis=1)

    ruin_level = initial_capital * ruin_threshold
    ruined = (equity_paths <= ruin_level).any(axis=1)
    finals = equity_paths[:, -1]

    return RuinReport(
        n_paths=n_paths,
        horizon_trades=horizon_trades,
        ruin_threshold=ruin_threshold,
        prob_ruin=float(ruined.mean()),
        median_final_equity=float(np.median(finals)),
        p5_final_equity=float(np.quantile(finals, 0.05)),
        p95_final_equity=float(np.quantile(finals, 0.95)),
    )
