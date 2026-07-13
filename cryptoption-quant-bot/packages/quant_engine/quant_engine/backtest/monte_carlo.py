"""Monte Carlo risk-of-ruin: resample empirical per-unit-stake PnL into many
alternative fixed-fraction paths and report ruin probability."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RuinReport:
    n_paths: int
    horizon_trades: int
    ruin_threshold: float
    prob_ruin: float
    median_final_equity: float
    p5_final_equity: float
    p95_final_equity: float

    def to_dict(self) -> dict:
        return self.__dict__


def ruin_probability(
    trade_log: pd.DataFrame, initial_capital: float, risk_fraction: float,
    n_paths: int = 5000, horizon_trades: int = 1000, ruin_threshold: float = 0.5,
    seed: int = 7,
) -> RuinReport:
    settled = trade_log[trade_log["outcome"].isin(["win", "loss"])]
    if settled.empty:
        return RuinReport(n_paths, horizon_trades, ruin_threshold,
                          float("nan"), float("nan"), float("nan"), float("nan"))
    unit = np.where(settled["outcome"].to_numpy() == "win",
                    settled["payout"].to_numpy(), -1.0)
    rng = np.random.default_rng(seed)
    draws = rng.choice(unit, size=(n_paths, horizon_trades), replace=True)
    equity = initial_capital * np.cumprod(1.0 + risk_fraction * draws, axis=1)
    ruined = (equity <= initial_capital * ruin_threshold).any(axis=1)
    finals = equity[:, -1]
    return RuinReport(
        n_paths=n_paths, horizon_trades=horizon_trades, ruin_threshold=ruin_threshold,
        prob_ruin=float(ruined.mean()), median_final_equity=float(np.median(finals)),
        p5_final_equity=float(np.quantile(finals, 0.05)),
        p95_final_equity=float(np.quantile(finals, 0.95)),
    )
