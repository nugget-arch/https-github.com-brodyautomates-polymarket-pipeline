"""Baseline strategies.

The random baseline is the null hypothesis every candidate must beat. The
trend / mean-reversion baselines are the "obvious" heuristics: if a fancy
model can't beat them out-of-sample, it has no business trading.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class RandomBaseline:
    """P(up) ~ U(0,1), independent of the data. Deterministic per (seed, n)."""

    name = "random"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001 - protocol
        return self

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        rng = np.random.default_rng(self.seed + len(X))
        return rng.uniform(0.0, 1.0, len(X))


class TrendBaseline:
    """Momentum-following: P(up) rises with EMA distance and short momentum."""

    name = "trend"
    _scale: float = 1.0

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001
        z = self._raw(X)
        sd = float(np.nanstd(z))
        self._scale = 1.0 / sd if sd > 0 else 1.0
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        cols = [c for c in ("f_ema_dist", "f_mom_5") if c in X.columns]
        if not cols:
            return np.zeros(len(X))
        return X[cols].sum(axis=1).to_numpy()

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._raw(X) * self._scale)


class MeanReversionBaseline:
    """Fade stretched moves: P(up) high when Bollinger z-score is very negative."""

    name = "meanrev"
    _scale: float = 1.0

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001
        z = self._raw(X)
        sd = float(np.nanstd(z))
        self._scale = 1.0 / sd if sd > 0 else 1.0
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        if "f_bb_z" not in X.columns:
            return np.zeros(len(X))
        return -X["f_bb_z"].fillna(0.0).to_numpy()

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._raw(X) * self._scale)
