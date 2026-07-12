"""End-to-end: synthetic data -> research pipeline -> verdict + report.

Two scenarios:
  * pure random walk  -> the platform MUST conclude "no edge";
  * injected AR(1) inefficiency (positive control) -> the pipeline must at
    least measure a materially better win rate for the model than for the
    random baseline (it may still fail candidacy on sample size, correctly).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from otc_lab.config import ExperimentConfig
from otc_lab.data.synthetic import make_asset_frame
from otc_lab.pipeline import NO_EDGE_SENTENCE, run_experiment
from otc_lab.report.builder import build_report


def _small_cfg(tmp_path: Path) -> ExperimentConfig:
    cfg = ExperimentConfig()
    cfg.labels.expiry_bars = [1]
    cfg.strategies.names = ["random", "logistic"]
    cfg.validation.train_bars = 1500
    cfg.validation.val_bars = 400
    cfg.validation.test_bars = 400
    cfg.validation.step_bars = 400
    cfg.validation.n_bootstrap = 200
    cfg.report.out_dir = str(tmp_path / "artifacts")
    cfg.registry_db = str(tmp_path / "artifacts" / "exp.sqlite")
    return cfg


def _dataset(edge: float) -> pd.DataFrame:
    a = make_asset_frame("EURUSD_OTC", 8000, seed=21, is_otc=True, edge_autocorr=edge)
    b = make_asset_frame("GBPUSD", 8000, seed=22, is_otc=False,
                         start_price=1.27, edge_autocorr=edge)
    return pd.concat([a, b], ignore_index=True)


def test_random_walk_yields_no_edge_verdict(tmp_path):
    cfg = _small_cfg(tmp_path)
    result = run_experiment(cfg, df=_dataset(edge=0.0))
    assert result.combos, "pipeline produced no combos"
    assert result.verdict == NO_EDGE_SENTENCE
    # report generation works and carries the sentence
    written = build_report(result)
    md = next(p for p in written if p.suffix == ".md").read_text()
    assert NO_EDGE_SENTENCE in md


def test_positive_control_detects_injected_signal(tmp_path):
    cfg = _small_cfg(tmp_path)
    result = run_experiment(cfg, df=_dataset(edge=0.35))
    logi = [c for c in result.combos if c.strategy == "logistic"]
    rand = [c for c in result.combos if c.strategy == "random"]
    assert logi and rand
    lw, rw = logi[0].metrics.win_rate, rand[0].metrics.win_rate
    assert np.isfinite(lw) and np.isfinite(rw)
    assert lw > rw + 0.05, (
        f"positive control failed: logistic {lw:.3f} not above random {rw:.3f}"
    )


def test_reproducibility_same_seed_same_results(tmp_path):
    cfg = _small_cfg(tmp_path)
    df = _dataset(edge=0.0)
    r1 = run_experiment(cfg, df=df.copy())
    r2 = run_experiment(cfg, df=df.copy())
    m1 = [(c.strategy, c.expiry_bars, c.metrics.n_trades, c.metrics.win_rate) for c in r1.combos]
    m2 = [(c.strategy, c.expiry_bars, c.metrics.n_trades, c.metrics.win_rate) for c in r2.combos]
    assert m1 == m2
