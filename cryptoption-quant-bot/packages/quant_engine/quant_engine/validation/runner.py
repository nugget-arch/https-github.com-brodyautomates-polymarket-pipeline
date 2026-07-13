"""Walk-forward runner.

For each (model, expiry) combo: fit per fold on train, calibrate on validation,
derive the decision threshold from VALIDATION uncertainty (never test), predict
on the fold's test slice, concatenate out-of-sample predictions, backtest them,
and compute metrics. Benjamini-Hochberg is applied across all non-baseline
combos so combos that look profitable by luck are rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..backtest import BinaryBacktestEngine, MetricsBundle, compute_metrics, decision_threshold
from ..backtest.engine import break_even_win_rate
from ..config import BacktestConfig, RiskConfig
from ..stats import benjamini_hochberg, wilson_ci
from ..strategies.base import make_model
from .splits import ValidationConfig, WalkForwardSplitter


def attach_features(labels: pd.DataFrame, feats: pd.DataFrame, fcols: list[str]) -> pd.DataFrame:
    """Join feature rows onto label samples by (asset, positional signal_idx)."""
    parts: list[pd.DataFrame] = []
    for asset, g in labels.groupby("asset", sort=False):
        fa = feats[feats["asset"] == asset].reset_index(drop=True)
        x = fa.iloc[g["signal_idx"].to_numpy()][fcols].reset_index(drop=True)
        parts.append(pd.concat([g.reset_index(drop=True), x], axis=1))
    out = pd.concat(parts, ignore_index=True)
    return out.dropna(subset=fcols).reset_index(drop=True)


@dataclass
class ComboResult:
    model: str
    expiry_bars: int
    threshold: float
    n_folds: int
    metrics: MetricsBundle
    fold_pnls: list[float]
    passed_bh: bool = False


@dataclass
class WalkForwardReport:
    combos: list[ComboResult] = field(default_factory=list)

    def best(self) -> ComboResult | None:
        ranked = [c for c in self.combos if np.isfinite(c.metrics.edge_over_breakeven)]
        return max(ranked, key=lambda c: c.metrics.edge_over_breakeven, default=None)


def _val_threshold(model, val: pd.DataFrame, fcols: list[str], bt_cfg: BacktestConfig) -> float:
    """Threshold from validation-set uncertainty (Wilson half-width), never test."""
    base = break_even_win_rate(bt_cfg.payout_floor) + bt_cfg.threshold_margin
    if val.empty:
        return decision_threshold(bt_cfg)
    p_val = model.predict_proba(val[fcols])
    sel = (p_val >= base) | (p_val <= 1 - base)
    if sel.sum() < 20:
        return decision_threshold(bt_cfg)
    y = val["y_up"].to_numpy()[sel]
    dir_up = p_val[sel] >= 0.5
    wins = int((dir_up == y.astype(bool)).sum())
    lo, hi = wilson_ci(wins, int(sel.sum()))
    return decision_threshold(bt_cfg, (hi - lo) / 2)


def run_walk_forward(
    samples: pd.DataFrame, fcols: list[str], model_names: list[str], expiry_bars: int,
    val_cfg: ValidationConfig, bt_cfg: BacktestConfig, risk_cfg: RiskConfig,
    seed: int = 7, n_bootstrap: int = 500,
) -> list[ComboResult]:
    splitter = WalkForwardSplitter(val_cfg)
    results: list[ComboResult] = []

    for name in model_names:
        oos_parts: list[pd.DataFrame] = []
        p_parts: list[np.ndarray] = []
        thresholds: list[float] = []
        n_folds = 0
        for fold in splitter.split(samples):
            train, val, test = samples[fold.train_mask], samples[fold.val_mask], samples[fold.test_mask]
            if train.empty or test.empty:
                continue
            model = make_model(name, seed=seed + fold.fold_id)
            model.fit(train[fcols], train["y_up"].to_numpy(),
                      val[fcols] if len(val) else None,
                      val["y_up"].to_numpy() if len(val) else None)
            thresholds.append(_val_threshold(model, val, fcols, bt_cfg))
            oos_parts.append(test)
            p_parts.append(model.predict_proba(test[fcols]))
            n_folds += 1

        if not oos_parts:
            continue
        oos = pd.concat(oos_parts, ignore_index=True)
        p_up = np.concatenate(p_parts)
        threshold = float(np.mean(thresholds)) if thresholds else decision_threshold(bt_cfg)

        res = BinaryBacktestEngine(bt_cfg, risk_cfg, seed).run(oos, p_up, threshold)
        metrics = compute_metrics(res.trade_log, risk_cfg.initial_capital, n_signals=len(oos),
                                  p_up_all=p_up, y_up_all=oos["y_up"].to_numpy(),
                                  n_bootstrap=n_bootstrap, seed=seed)
        results.append(ComboResult(
            model=name, expiry_bars=expiry_bars, threshold=threshold, n_folds=n_folds,
            metrics=metrics, fold_pnls=_fold_pnls(res.trade_log)))
    return results


def _fold_pnls(trade_log: pd.DataFrame, n_chunks: int = 3) -> list[float]:
    if trade_log.empty or "outcome" not in trade_log.columns:
        return []
    settled = trade_log[trade_log["outcome"].isin(["win", "loss"])].sort_values("ts_utc")
    if settled.empty:
        return []
    bounds = np.linspace(0, len(settled), n_chunks + 1, dtype=int)
    return [float(settled.iloc[lo:hi]["pnl"].sum())
            for lo, hi in zip(bounds[:-1], bounds[1:], strict=False) if hi > lo]


def apply_multiple_testing(combos: list[ComboResult], method: str = "benjamini_hochberg") -> None:
    """Set passed_bh on each non-baseline combo, correcting for multiplicity."""
    testable = [c for c in combos if c.model != "random"]
    pvals = [c.metrics.pvalue_vs_breakeven for c in testable]
    rejects = benjamini_hochberg(pvals) if method == "benjamini_hochberg" else [
        p < 0.05 / max(len(pvals), 1) for p in pvals
    ]
    for c, rej in zip(testable, rejects, strict=False):
        c.passed_bh = bool(rej)
