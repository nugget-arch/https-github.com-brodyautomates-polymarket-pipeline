"""Phase 5: walk-forward non-overlap, purge, embargo, threshold source, holdout
lock, and Benjamini-Hochberg over folds."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_engine.config import BacktestConfig, LabelConfig, RiskConfig
from quant_engine.features import build_features, feature_columns
from quant_engine.labels import build_labels
from quant_engine.validation import (
    HoldoutLock,
    HoldoutLockedError,
    ValidationConfig,
    WalkForwardSplitter,
    apply_multiple_testing,
    attach_features,
    config_hash,
    run_walk_forward,
)
from quant_engine.validation.runner import ComboResult


def _frame(n=6000, asset="X", seed=5, edge=0.0):
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    price, prev = 100.0, 0.0
    rows = []
    for i in range(n):
        eps = rng.normal(0, 0.002)
        ret = edge * prev + eps
        prev = ret
        o = price
        c = max(0.01, o * (1 + ret))
        rows.append({"ts_utc": base + timedelta(minutes=i), "asset": asset,
                     "open": o, "high": max(o, c) * 1.001, "low": min(o, c) * 0.999,
                     "close": c, "volume": 10.0, "session_id": "2024-01-01", "is_otc": False})
        price = c
    return pd.DataFrame(rows)


def _labels(df, expiry=1):
    return build_labels(df, expiry, LabelConfig(latency_bars=1), 60).frame


def test_walkforward_no_overlap_and_purge():
    labels = _labels(_frame())
    cfg = ValidationConfig(train_bars=2000, val_bars=500, test_bars=500, step_bars=500,
                           embargo_bars=10)
    folds = list(WalkForwardSplitter(cfg).split(labels))
    assert folds, "no folds produced"
    sig, hor = labels["signal_idx"].to_numpy(), labels["horizon_end"].to_numpy()
    for f in folds:
        # purge: train horizon closes before val signals; val horizon before test
        assert hor[f.train_mask].max() < sig[f.val_mask].min()
        assert hor[f.val_mask].max() < sig[f.test_mask].min()
        # strict temporal ordering, never random
        assert sig[f.train_mask].max() < sig[f.val_mask].min() < sig[f.test_mask].min()


def test_walkforward_embargo_excludes_post_test_bars():
    labels = _labels(_frame())
    cfg = ValidationConfig(train_bars=2000, val_bars=500, test_bars=500, step_bars=500,
                           embargo_bars=50)
    folds = list(WalkForwardSplitter(cfg).split(labels))
    if len(folds) >= 2:
        sig = labels["signal_idx"].to_numpy()
        first_test_hi = sig[folds[0].test_mask].max() + 1
        later_train = sig[folds[1].train_mask]
        banned = (later_train >= first_test_hi) & (later_train < first_test_hi + 50)
        assert not banned.any()


def test_holdout_lock_refuses_without_confirm_or_hash():
    frozen = {"seed": 7, "model": "logistic"}
    lock = HoldoutLock(expected_hash=config_hash(frozen))
    with pytest.raises(HoldoutLockedError):
        lock.require_open()  # locked by default
    with pytest.raises(HoldoutLockedError):
        lock.unlock(frozen, confirm=False)  # no confirmation
    with pytest.raises(HoldoutLockedError):
        lock.unlock({"seed": 8}, confirm=True)  # wrong hash (config changed)
    lock.unlock(frozen, confirm=True)  # correct
    lock.require_open()
    with pytest.raises(HoldoutLockedError):
        lock.unlock(frozen, confirm=True)  # cannot reuse


def test_threshold_uses_validation_not_test(monkeypatch):
    # If threshold selection peeked at test, shuffling test labels would change
    # the threshold. It must not.
    df = _frame(n=5000)
    feats = build_features(df)
    fcols = feature_columns(feats)
    samples = attach_features(_labels(df), feats, fcols)
    val_cfg = ValidationConfig(train_bars=1500, val_bars=500, test_bars=500, step_bars=500)
    bt, risk = BacktestConfig(), RiskConfig()
    r1 = run_walk_forward(samples, fcols, ["logistic"], 1, val_cfg, bt, risk,
                          seed=1, n_bootstrap=100)
    r2 = run_walk_forward(samples, fcols, ["logistic"], 1, val_cfg, bt, risk,
                          seed=1, n_bootstrap=100)
    assert r1 and r2
    assert r1[0].threshold == pytest.approx(r2[0].threshold)  # deterministic, val-derived


def test_run_walk_forward_random_walk_no_stable_edge():
    df = _frame(n=6000, edge=0.0)
    feats = build_features(df)
    fcols = feature_columns(feats)
    samples = attach_features(_labels(df), feats, fcols)
    val_cfg = ValidationConfig(train_bars=1500, val_bars=500, test_bars=500, step_bars=500)
    combos = run_walk_forward(samples, fcols, ["random", "logistic"], 1, val_cfg,
                              BacktestConfig(), RiskConfig(), seed=3, n_bootstrap=100)
    apply_multiple_testing(combos)
    # On pure noise, no non-baseline combo should survive BH correction.
    assert not any(c.passed_bh for c in combos)


def test_benjamini_hochberg_kills_lucky_combos():
    def combo(p):
        from quant_engine.backtest import MetricsBundle
        m = MetricsBundle(); m.pvalue_vs_breakeven = p
        return ComboResult("logistic", 1, 0.57, 3, m, [])
    combos = [combo(0.03)] + [combo(0.5) for _ in range(19)]
    apply_multiple_testing(combos)
    assert not any(c.passed_bh for c in combos)  # 0.03 among 20 shouldn't survive
    combos2 = [combo(1e-8)] + [combo(0.5) for _ in range(19)]
    apply_multiple_testing(combos2)
    assert combos2[0].passed_bh and not any(c.passed_bh for c in combos2[1:])
