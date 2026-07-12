"""Mandatory metrics for every evaluation, as a serialisable bundle."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from ..config import break_even_win_rate
from ..validation.stats import (
    block_bootstrap_ci,
    binomial_pvalue_vs_breakeven,
    brier_score,
    calibration_table,
    log_loss_score,
    wilson_ci,
)


@dataclass
class MetricsBundle:
    n_signals: int = 0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_ties: int = 0
    n_rejected: int = 0
    n_blocked: int = 0
    win_rate: float = float("nan")
    break_even_rate: float = float("nan")
    edge_over_breakeven: float = float("nan")
    win_rate_ci_lo: float = float("nan")
    win_rate_ci_hi: float = float("nan")
    bootstrap_pnl_lo: float = float("nan")
    bootstrap_pnl_hi: float = float("nan")
    pvalue_vs_breakeven: float = 1.0
    expected_value_per_trade: float = float("nan")
    net_profit: float = 0.0
    max_drawdown: float = 0.0
    max_loss_streak: int = 0
    avg_payout: float = float("nan")
    brier: float = float("nan")
    log_loss: float = float("nan")
    calibration: list[dict] = field(default_factory=list)
    by_asset: dict[str, dict] = field(default_factory=dict)
    by_hour: dict[str, dict] = field(default_factory=dict)
    by_regime: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _streaks(outcomes: pd.Series) -> int:
    streak = worst = 0
    for o in outcomes:
        if o == "loss":
            streak += 1
            worst = max(worst, streak)
        elif o == "win":
            streak = 0
    return worst


def _drawdown(capital: pd.Series, initial: float) -> float:
    eq = pd.concat([pd.Series([initial]), capital], ignore_index=True)
    peak = eq.cummax()
    dd = ((peak - eq) / peak).max()
    return float(dd) if np.isfinite(dd) else 0.0


def _subgroup(trades: pd.DataFrame, payout_mean: float) -> dict:
    n = len(trades)
    wins = int((trades["outcome"] == "win").sum())
    be = break_even_win_rate(payout_mean) if payout_mean > 0 else float("nan")
    wr = wins / n if n else float("nan")
    lo, hi = wilson_ci(wins, n)
    return {
        "n": n, "win_rate": wr, "break_even": be,
        "edge": (wr - be) if n else float("nan"),
        "ci_lo": lo, "ci_hi": hi,
        "net_pnl": float(trades["pnl"].sum()),
    }


def compute_metrics(
    trade_log: pd.DataFrame,
    initial_capital: float,
    n_signals: int,
    p_up_all: np.ndarray | None = None,
    y_up_all: np.ndarray | None = None,
    vol_feature: pd.Series | None = None,
    n_bootstrap: int = 2000,
    block_size: int = 50,
    confidence: float = 0.95,
    seed: int = 7,
) -> MetricsBundle:
    m = MetricsBundle(n_signals=n_signals)
    if trade_log.empty:
        return m

    executed = trade_log[trade_log["outcome"].isin(["win", "loss", "tie"])]
    settled = executed[executed["outcome"].isin(["win", "loss"])]

    m.n_trades = len(settled)
    m.n_wins = int((settled["outcome"] == "win").sum())
    m.n_losses = int((settled["outcome"] == "loss").sum())
    m.n_ties = int((executed["outcome"] == "tie").sum())
    m.n_rejected = int((trade_log["outcome"] == "rejected").sum())
    m.n_blocked = int(trade_log["outcome"].str.startswith("blocked").sum())

    if m.n_trades:
        m.win_rate = m.n_wins / m.n_trades
        m.avg_payout = float(settled["payout"].mean())
        m.break_even_rate = break_even_win_rate(m.avg_payout)
        m.edge_over_breakeven = m.win_rate - m.break_even_rate
        m.win_rate_ci_lo, m.win_rate_ci_hi = wilson_ci(m.n_wins, m.n_trades, confidence)
        m.pvalue_vs_breakeven = binomial_pvalue_vs_breakeven(
            m.n_wins, m.n_trades, m.break_even_rate
        )
        m.expected_value_per_trade = float(settled["pnl"].mean())
        m.net_profit = float(executed["pnl"].sum())
        m.max_drawdown = _drawdown(executed["capital_after"], initial_capital)
        m.max_loss_streak = _streaks(executed["outcome"])

        pnl_ci = block_bootstrap_ci(
            settled["pnl"].to_numpy(), n_boot=n_bootstrap,
            block_size=block_size, confidence=confidence, seed=seed,
        )
        m.bootstrap_pnl_lo, m.bootstrap_pnl_hi = pnl_ci.lo, pnl_ci.hi

        # breakdowns
        for asset, g in settled.groupby("asset"):
            m.by_asset[str(asset)] = _subgroup(g, float(g["payout"].mean()))
        hours = pd.to_datetime(settled["timestamp"]).dt.hour
        for hr, g in settled.groupby(hours):
            m.by_hour[f"{int(hr):02d}"] = _subgroup(g, float(g["payout"].mean()))

    # probability quality on ALL evaluated signals (not only executed trades)
    if p_up_all is not None and y_up_all is not None and len(p_up_all):
        m.brier = brier_score(p_up_all, y_up_all)
        m.log_loss = log_loss_score(p_up_all, y_up_all)
        m.calibration = calibration_table(p_up_all, y_up_all)

    # volatility regimes: causal regime label carried through the trade log
    if m.n_trades and "regime" in settled.columns:
        for regime, g in settled.groupby("regime"):
            if len(g) and str(regime) != "all":
                m.by_regime[str(regime)] = _subgroup(g, float(g["payout"].mean()))

    return m
