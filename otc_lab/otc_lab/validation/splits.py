"""Temporal walk-forward splitting with purge and embargo.

NEVER random splits: samples are ordered in time per asset, and folds are
built on bar positions. Leakage controls:

  * PURGE — a training sample whose outcome window (signal_idx..horizon_end)
    overlaps the validation or test range is dropped: its label contains
    information from inside the evaluation period.
  * EMBARGO — an extra `embargo_bars` buffer after each evaluation range is
    excluded from any later training window, damping serial-correlation
    leakage between adjacent folds.

The FINAL holdout (last fraction of each asset) is separated earlier, in
`data.loader.split_holdout`, and stays locked until research is frozen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd

from ..config import ValidationConfig


@dataclass
class Fold:
    fold_id: int
    asset: str
    train_mask: np.ndarray
    val_mask: np.ndarray
    test_mask: np.ndarray


class WalkForwardSplitter:
    """Yields per-asset folds over a label frame (needs signal_idx/horizon_end)."""

    def __init__(self, cfg: ValidationConfig):
        self.cfg = cfg

    def split(self, labels: pd.DataFrame) -> Iterator[Fold]:
        cfg = self.cfg
        fold_id = 0
        for asset, g in labels.groupby("asset", sort=False):
            sig = g["signal_idx"].to_numpy()
            hor = g["horizon_end"].to_numpy()
            n_bars = int(hor.max()) + 1 if len(hor) else 0

            prior_test_ends: list[int] = []  # test_hi of earlier folds (this asset)
            start = 0
            while True:
                train_lo = start
                train_hi = train_lo + cfg.train_bars          # [lo, hi)
                val_lo = train_hi
                val_hi = val_lo + cfg.val_bars
                test_lo = val_hi
                test_hi = test_lo + cfg.test_bars
                if test_hi > n_bars:
                    break

                # PURGE: a train sample's horizon must end before validation starts
                train_mask = (sig >= train_lo) & (hor < val_lo)
                # purge between val and test as well
                val_mask = (sig >= val_lo) & (hor < test_lo)
                test_mask = (sig >= test_lo) & (hor < test_hi)

                # EMBARGO: exclude train samples in the embargo_bars right after
                # any earlier fold's test window (serial-correlation buffer).
                for prev_hi in prior_test_ends:
                    train_mask &= ~((sig >= prev_hi) & (sig < prev_hi + cfg.embargo_bars))

                if train_mask.sum() > 100 and val_mask.sum() > 30 and test_mask.sum() > 30:
                    yield Fold(
                        fold_id=fold_id,
                        asset=str(asset),
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


def apply_embargo(train_mask: np.ndarray, sig: np.ndarray,
                  eval_lo: int, embargo_bars: int) -> np.ndarray:
    """Drop training samples whose signal falls in [eval_lo - embargo, eval_lo)."""
    keep = ~((sig >= eval_lo - embargo_bars) & (sig < eval_lo))
    return train_mask & keep
