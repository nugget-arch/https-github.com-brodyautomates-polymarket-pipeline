import numpy as np
import pandas as pd

from otc_lab.config import LabelConfig, ValidationConfig
from otc_lab.labels.binary import build_labels
from otc_lab.validation.splits import WalkForwardSplitter
from otc_lab.validation.stats import (
    block_bootstrap_ci,
    binomial_pvalue_vs_breakeven,
    multiple_test_correction,
    wilson_ci,
)


def test_walkforward_no_temporal_overlap(candles):
    labels = build_labels(candles, expiry_bars=3, cfg=LabelConfig(latency_bars=1)).frame
    cfg = ValidationConfig(train_bars=800, val_bars=200, test_bars=200,
                           step_bars=200, embargo_bars=10)
    folds = list(WalkForwardSplitter(cfg).split(labels))
    assert folds, "no folds produced"
    sig = labels["signal_idx"].to_numpy()
    hor = labels["horizon_end"].to_numpy()
    for f in folds:
        # PURGE: every train horizon closes before the earliest val signal
        assert hor[f.train_mask].max() < sig[f.val_mask].min()
        # and every val horizon closes before the earliest test signal
        assert hor[f.val_mask].max() < sig[f.test_mask].min()
        # temporal ordering, never random
        assert sig[f.train_mask].max() < sig[f.val_mask].min()
        assert sig[f.val_mask].max() < sig[f.test_mask].min()


def test_walkforward_embargo_excludes_post_test_bars(candles):
    labels = build_labels(candles, expiry_bars=1, cfg=LabelConfig(latency_bars=1)).frame
    cfg = ValidationConfig(train_bars=800, val_bars=200, test_bars=200,
                           step_bars=200, embargo_bars=50)
    folds = list(WalkForwardSplitter(cfg).split(labels))
    if len(folds) >= 2:
        sig = labels["signal_idx"].to_numpy()
        first_test_hi = sig[folds[0].test_mask].max() + 1
        later_train = sig[folds[1].train_mask]
        banned = (later_train >= first_test_hi) & (later_train < first_test_hi + 50)
        assert not banned.any(), "embargo violated"


def test_wilson_ci_contains_point():
    lo, hi = wilson_ci(60, 100)
    assert lo < 0.6 < hi
    lo0, hi0 = wilson_ci(0, 0)
    assert (lo0, hi0) == (0.0, 1.0)


def test_block_bootstrap_ci_sane():
    rng = np.random.default_rng(0)
    x = rng.normal(0.1, 1.0, 2000)
    ci = block_bootstrap_ci(x, n_boot=500, block_size=50)
    assert ci.lo < ci.point < ci.hi
    assert ci.lo < 0.1 < ci.hi  # true mean inside 95% CI (should hold here)


def test_binomial_pvalue_directions():
    # clearly above break-even -> small p; at break-even -> large p
    assert binomial_pvalue_vs_breakeven(700, 1000, 0.5556) < 1e-6
    assert binomial_pvalue_vs_breakeven(556, 1000, 0.5556) > 0.4


def test_multiple_testing_kills_lucky_strategies():
    # 20 hypotheses, one barely "significant" at 0.03: BH must not reject it
    pvals = [0.03] + [0.5] * 19
    rejects = multiple_test_correction(pvals, "benjamini_hochberg")
    assert not any(rejects)
    # a truly strong result survives
    pvals = [1e-8] + [0.5] * 19
    rejects = multiple_test_correction(pvals, "benjamini_hochberg")
    assert rejects[0] and not any(rejects[1:])
