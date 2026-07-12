"""Research pipeline: data -> features -> labels -> walk-forward -> backtest
-> statistics -> verdict.

The verdict logic implements the candidate criteria from the project charter.
If any criterion fails, the strategy is NOT declared valid and the report
carries the sentence: "NO SE HA DEMOSTRADO UNA VENTAJA ESTADÍSTICA OPERABLE".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest.engine import BinaryBacktestEngine, decision_threshold
from .backtest.metrics import MetricsBundle, compute_metrics
from .backtest.monte_carlo import RuinReport, ruin_probability
from .config import ExperimentConfig, break_even_win_rate
from .data.loader import load_candles, split_holdout
from .data.validate import validate_candles
from .features.engine import build_features, feature_columns
from .labels.binary import build_labels
from .logging_setup import get_logger, setup_logging
from .strategies.base import make_strategy
from .validation.splits import WalkForwardSplitter
from .validation.stats import multiple_test_correction, wilson_ci

log = get_logger("pipeline")

NO_EDGE_SENTENCE = "NO SE HA DEMOSTRADO UNA VENTAJA ESTADÍSTICA OPERABLE"


@dataclass
class ComboResult:
    strategy: str
    expiry_bars: int
    threshold: float
    metrics: MetricsBundle
    metrics_ideal: MetricsBundle          # before costs (no rejections, fixed payout)
    trade_log: pd.DataFrame
    fold_pnls: list[float]
    criteria: dict[str, bool] = field(default_factory=dict)
    criteria_notes: dict[str, str] = field(default_factory=dict)
    passed_bh: bool = False
    ruin: RuinReport | None = None

    @property
    def is_candidate(self) -> bool:
        return bool(self.criteria) and all(self.criteria.values())


@dataclass
class ExperimentResult:
    config: ExperimentConfig
    combos: list[ComboResult]
    verdict: str
    validation_report: str
    n_bars_research: int
    n_bars_holdout: int

    @property
    def any_candidate(self) -> bool:
        return any(c.is_candidate for c in self.combos)


def _attach_features(labels: pd.DataFrame, feats: pd.DataFrame, fcols: list[str]) -> pd.DataFrame:
    """Join feature rows (by asset + positional signal_idx) onto label samples."""
    parts: list[pd.DataFrame] = []
    for asset, g in labels.groupby("asset", sort=False):
        fa = feats[feats["asset"] == asset].reset_index(drop=True)
        x = fa.iloc[g["signal_idx"].to_numpy()][fcols].reset_index(drop=True)
        merged = pd.concat([g.reset_index(drop=True), x], axis=1)
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    return out.dropna(subset=fcols).reset_index(drop=True)


def _oos_predict(
    cfg: ExperimentConfig, samples: pd.DataFrame, fcols: list[str], strategy_name: str
) -> tuple[pd.DataFrame, np.ndarray, float]:
    """Walk-forward: fit per fold, predict on that fold's test slice.

    Returns (OOS samples, aligned p_up, mean validation CI half-width)."""
    splitter = WalkForwardSplitter(cfg.validation)
    oos_parts: list[pd.DataFrame] = []
    p_parts: list[np.ndarray] = []
    val_halfwidths: list[float] = []

    for fold in splitter.split(samples):
        train = samples[fold.train_mask]
        val = samples[fold.val_mask]
        test = samples[fold.test_mask]
        if train.empty or test.empty:
            continue

        strat = make_strategy(strategy_name, cfg.strategies, cfg.seed + fold.fold_id)
        strat.fit(train[fcols], train["y_up"].to_numpy(),
                  val[fcols] if len(val) else None,
                  val["y_up"].to_numpy() if len(val) else None)

        # validation-derived uncertainty for the threshold (test never touched)
        if len(val):
            p_val = strat.predict_proba_up(val[fcols])
            base_thr = break_even_win_rate(cfg.backtest.payout_floor) + cfg.backtest.threshold_margin
            sel = (p_val >= base_thr) | (p_val <= 1 - base_thr)
            if sel.sum() >= 20:
                y_sel = val["y_up"].to_numpy()[sel]
                dir_up = p_val[sel] >= 0.5
                wins = int((dir_up == y_sel.astype(bool)).sum())
                lo, hi = wilson_ci(wins, int(sel.sum()), cfg.validation.confidence)
                val_halfwidths.append((hi - lo) / 2)

        p_test = strat.predict_proba_up(test[fcols])
        oos_parts.append(test)
        p_parts.append(p_test)

    if not oos_parts:
        empty = samples.iloc[0:0]
        return empty, np.array([]), 0.0
    oos = pd.concat(oos_parts, ignore_index=True)
    p_up = np.concatenate(p_parts)
    val_hw = float(np.mean(val_halfwidths)) if val_halfwidths else 0.0
    return oos, p_up, val_hw


def _fold_pnls(trade_log: pd.DataFrame, n_chunks: int = 3) -> list[float]:
    """Net PnL of the OOS period split into temporal thirds (stability check)."""
    settled = trade_log[trade_log["outcome"].isin(["win", "loss"])].sort_values("timestamp")
    if settled.empty:
        return []
    bounds = np.linspace(0, len(settled), n_chunks + 1, dtype=int)
    return [
        float(settled.iloc[lo:hi]["pnl"].sum())
        for lo, hi in zip(bounds[:-1], bounds[1:])
        if hi > lo
    ]


def _apply_criteria(cfg: ExperimentConfig, combo: ComboResult,
                    baseline: MetricsBundle | None) -> None:
    """Candidate criteria checklist. ALL must pass."""
    m = combo.metrics
    crit = combo.criteria
    notes = combo.criteria_notes
    vcfg = cfg.validation

    crit["min_oos_trades"] = m.n_trades >= vcfg.min_oos_trades
    notes["min_oos_trades"] = f"{m.n_trades} >= {vcfg.min_oos_trades}"

    crit["edge_after_costs"] = (
        np.isfinite(m.edge_over_breakeven) and m.edge_over_breakeven > 0
    )
    notes["edge_after_costs"] = (
        f"edge {m.edge_over_breakeven:+.4f} (win {m.win_rate:.4f} vs BE {m.break_even_rate:.4f})"
        if np.isfinite(m.edge_over_breakeven) else "no settled trades"
    )

    crit["ci_near_breakeven"] = (
        np.isfinite(m.win_rate_ci_lo) and m.win_rate_ci_lo >= m.break_even_rate - 0.01
    )
    notes["ci_near_breakeven"] = (
        f"CI lower {m.win_rate_ci_lo:.4f} vs BE-1pt {m.break_even_rate - 0.01:.4f}"
        if np.isfinite(m.win_rate_ci_lo) else "n/a"
    )

    crit["multiple_testing"] = combo.passed_bh
    notes["multiple_testing"] = f"BH-corrected significance: {combo.passed_bh}"

    stable = combo.fold_pnls
    crit["stable_over_periods"] = len(stable) >= 2 and sum(p > 0 for p in stable) >= max(2, len(stable) - 1)
    notes["stable_over_periods"] = f"period PnLs: {[round(p, 2) for p in stable]}"

    pos_assets = [a for a, s in m.by_asset.items() if s["n"] >= 100 and s["edge"] > 0]
    crit["not_single_asset"] = len(m.by_asset) >= 2 and len(pos_assets) >= 2
    notes["not_single_asset"] = f"assets with n>=100 & edge>0: {pos_assets}"

    if m.by_hour and m.net_profit > 0:
        best_share = max(
            (s["net_pnl"] / m.net_profit) for s in m.by_hour.values() if s["net_pnl"] > 0
        ) if any(s["net_pnl"] > 0 for s in m.by_hour.values()) else 1.0
        crit["not_single_hour"] = best_share < 0.6
        notes["not_single_hour"] = f"max hourly profit share {best_share:.2f} < 0.60"
    else:
        crit["not_single_hour"] = False
        notes["not_single_hour"] = "no positive profit to attribute"

    if baseline is not None and np.isfinite(m.win_rate) and np.isfinite(baseline.win_rate):
        crit["beats_random_baseline"] = (
            m.win_rate > baseline.win_rate and m.net_profit > baseline.net_profit
        )
        notes["beats_random_baseline"] = (
            f"win {m.win_rate:.4f} vs random {baseline.win_rate:.4f}; "
            f"pnl {m.net_profit:.2f} vs {baseline.net_profit:.2f}"
        )
    else:
        crit["beats_random_baseline"] = False
        notes["beats_random_baseline"] = "baseline unavailable"

    if combo.ruin is not None and np.isfinite(combo.ruin.prob_ruin):
        crit["survives_monte_carlo"] = combo.ruin.prob_ruin < 0.05
        notes["survives_monte_carlo"] = f"P(ruin) {combo.ruin.prob_ruin:.4f} < 0.05"
    else:
        crit["survives_monte_carlo"] = False
        notes["survives_monte_carlo"] = "no MC result"

    crit["drawdown_compatible"] = m.max_drawdown <= 0.10
    notes["drawdown_compatible"] = f"max DD {m.max_drawdown:.4f} <= 0.10"


def run_experiment(cfg: ExperimentConfig, df: pd.DataFrame | None = None) -> ExperimentResult:
    setup_logging(cfg.log_level)
    np.random.seed(cfg.seed)

    if df is None:
        df = load_candles(cfg.data.paths, cfg.data)
    df, vreport = validate_candles(df, cfg.data)
    research, holdout = split_holdout(df, cfg.data)
    log.info("data split", extra={"ctx_research": len(research), "ctx_holdout": len(holdout)})

    feats = build_features(research, cfg.features)
    fcols = feature_columns(feats)

    strategy_names = list(cfg.strategies.names)
    if cfg.strategies.use_lightgbm and "lightgbm" not in strategy_names:
        strategy_names.append("lightgbm")

    combos: list[ComboResult] = []
    baselines_by_expiry: dict[int, MetricsBundle] = {}

    for expiry in cfg.labels.expiry_bars:
        labels = build_labels(research, expiry, cfg.labels, cfg.data.bar_seconds)
        samples = _attach_features(labels.frame, feats, fcols)
        if samples.empty:
            continue

        for name in strategy_names:
            oos, p_up, val_hw = _oos_predict(cfg, samples, fcols, name)
            if oos.empty:
                continue
            # volatility regime label (causal feature, terciles over OOS period)
            if "f_realized_vol" in oos.columns:
                try:
                    oos = oos.assign(regime=pd.qcut(
                        oos["f_realized_vol"], 3,
                        labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop",
                    ).astype(str))
                except ValueError:
                    oos = oos.assign(regime="all")
            threshold = decision_threshold(cfg.backtest, val_hw)

            engine = BinaryBacktestEngine(cfg.backtest, cfg.risk, cfg.seed, cfg.labels.tie_policy)
            trade_log = engine.run(oos, p_up, threshold)

            # ideal run: no rejections, fixed payout (before-costs comparison)
            ideal_cfg = cfg.backtest.model_copy(update={"rejection_prob": 0.0, "payout_jitter": 0.0})
            ideal_log = BinaryBacktestEngine(ideal_cfg, cfg.risk, cfg.seed, cfg.labels.tie_policy).run(
                oos, p_up, threshold
            )

            metrics = compute_metrics(
                trade_log, cfg.risk.initial_capital, n_signals=len(oos),
                p_up_all=p_up, y_up_all=oos["y_up"].to_numpy(),
                n_bootstrap=cfg.validation.n_bootstrap,
                block_size=cfg.validation.block_size,
                confidence=cfg.validation.confidence, seed=cfg.seed,
            )
            metrics_ideal = compute_metrics(
                ideal_log, cfg.risk.initial_capital, n_signals=len(oos),
                n_bootstrap=200, seed=cfg.seed,
            )

            combo = ComboResult(
                strategy=name, expiry_bars=expiry, threshold=threshold,
                metrics=metrics, metrics_ideal=metrics_ideal,
                trade_log=trade_log, fold_pnls=_fold_pnls(trade_log),
            )
            combo.ruin = ruin_probability(
                trade_log, cfg.risk.initial_capital, cfg.risk.risk_per_trade,
                seed=cfg.seed,
            )
            combos.append(combo)
            if name == "random":
                baselines_by_expiry[expiry] = metrics
            log.info("combo done", extra={
                "ctx_strategy": name, "ctx_expiry": expiry,
                "ctx_trades": metrics.n_trades,
                "ctx_win_rate": round(metrics.win_rate, 4) if np.isfinite(metrics.win_rate) else None,
            })

    # multiplicity correction across every non-baseline combo compared
    testable = [c for c in combos if c.strategy != "random"]
    pvals = [c.metrics.pvalue_vs_breakeven for c in testable]
    rejects = multiple_test_correction(pvals, cfg.validation.multiple_test_method)
    for c, rej in zip(testable, rejects):
        c.passed_bh = bool(rej)

    for c in combos:
        _apply_criteria(cfg, c, baselines_by_expiry.get(c.expiry_bars))

    verdict = (
        "CANDIDATA: al menos una combinación supera TODOS los criterios; "
        "queda pendiente la prueba final bloqueada (holdout)."
        if any(c.is_candidate for c in combos)
        else NO_EDGE_SENTENCE
    )

    return ExperimentResult(
        config=cfg, combos=combos, verdict=verdict,
        validation_report=vreport.summary(),
        n_bars_research=len(research), n_bars_holdout=len(holdout),
    )
