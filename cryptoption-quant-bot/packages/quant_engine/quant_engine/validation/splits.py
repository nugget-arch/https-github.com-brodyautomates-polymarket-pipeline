"""Temporal walk-forward splitting with purge and embargo.

NEVER random: samples are ordered by bar position per asset, and folds are
built on bar ranges. Leakage controls:

  * PURGE — a training sample whose outcome window (signal_idx..horizon_end)
    overlaps the validation/test range is dropped: its label contains
    information from inside the evaluation period.
  * EMBARGO — an extra `embargo_bars` buffer after each earlier fold's test
    window is excluded from later training, damping serial-correlation leakage.

The FINAL holdout is separated earlier (data.split_holdout equivalent) and
stays locked until research is frozen (see holdout.py).
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ValidationConfig:
    train_bars: int = 5000
    val_bars: int = 1000
    test_bars: int = 1000
    step_bars: int = 1000
    embargo_bars: int = 30
    min_train: int = 100
    min_eval: int = 30


@dataclass
class Fold:
    fold_id: int
    asset: str
    train_mask: np.ndarray
    val_mask: np.ndarray
    test_mask: np.ndarray


class WalkForwardSplitter:
    def __init__(self, cfg: ValidationConfig):
        self.cfg = cfg

    def split(self, labels: pd.DataFrame) -> Iterator[Fold]:
        cfg = self.cfg
        fold_id = 0
        for asset, g in labels.groupby("asset", sort=False):
            sig = g["signal_idx"].to_numpy()
            hor = g["horizon_end"].to_numpy()
            n_bars = int(hor.max()) + 1 if len(hor) else 0
            prior_test_ends: list[int] = []
            start = 0
            while True:
                train_lo, train_hi = start, start + cfg.train_bars
                val_lo, val_hi = train_hi, train_hi + cfg.val_bars
                test_lo, test_hi = val_hi, val_hi + cfg.test_bars
                if test_hi > n_bars:
                    break

                # PURGE: train horizon must close before validation starts;
                # val horizon must close before test starts.
                train_mask = (sig >= train_lo) & (hor < val_lo)
                val_mask = (sig >= val_lo) & (hor < test_lo)
                test_mask = (sig >= test_lo) & (hor < test_hi)

                # EMBARGO: drop train samples inside the embargo window right
                # after any earlier fold's test range.
                for prev_hi in prior_test_ends:
                    train_mask &= ~((sig >= prev_hi) & (sig < prev_hi + cfg.embargo_bars))

                if (train_mask.sum() > cfg.min_train and val_mask.sum() > cfg.min_eval
                        and test_mask.sum() > cfg.min_eval):
                    yield Fold(
                        fold_id=fold_id, asset=str(asset),
                        train_mask=self._to_global(labels, g, train_mask),
                        val_mask=self._to_global(labels, g, val_mask),
                        test_mask=self._to_global(labels, g, test_mask),
                    )
                    fold_id += 1
                    prior_test_ends.append(test_hi)
                start += max(cfg.step_bars, 1)

    @staticmethod
    def _to_global(labels: pd.DataFrame, g: pd.DataFrame, local_mask: np.ndarray) -> np.ndarray:
        mask = np.zeros(len(labels), dtype=bool)
        mask[g.index[local_mask]] = True
        return mask
