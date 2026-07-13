"""Baseline models. `random` is the null hypothesis every candidate must beat;
trend/meanrev are the obvious heuristics a real model must also beat OOS."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class _BaselineMixin:
    name = "baseline"
    _schema: list[str] = []
    _meta: dict[str, Any] = {}

    def get_version(self) -> str:
        return f"{self.name}-1.0.0"

    def get_feature_schema(self) -> list[str]:
        return list(self._schema)

    def get_training_metadata(self) -> dict[str, Any]:
        return dict(self._meta)


class RandomBaseline(_BaselineMixin):
    name = "random"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001
        self._schema = list(X.columns)
        self._meta = {"n_train": int(len(X)), "seed": self.seed}
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        rng = np.random.default_rng(self.seed + len(X))
        return rng.uniform(0.0, 1.0, len(X))


class TrendBaseline(_BaselineMixin):
    name = "trend"
    _scale: float = 1.0

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001
        self._schema = list(X.columns)
        z = self._raw(X)
        sd = float(np.nanstd(z))
        self._scale = 1.0 / sd if sd > 0 else 1.0
        self._meta = {"n_train": int(len(X)), "scale": self._scale}
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        cols = [c for c in ("f_ema_dist", "f_mom_5") if c in X.columns]
        return X[cols].sum(axis=1).to_numpy() if cols else np.zeros(len(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._raw(X) * self._scale)


class MeanReversionBaseline(_BaselineMixin):
    name = "meanrev"
    _scale: float = 1.0

    def fit(self, X, y, X_val=None, y_val=None):  # noqa: ANN001
        self._schema = list(X.columns)
        z = self._raw(X)
        sd = float(np.nanstd(z))
        self._scale = 1.0 / sd if sd > 0 else 1.0
        self._meta = {"n_train": int(len(X)), "scale": self._scale}
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        return -X["f_bb_z"].fillna(0.0).to_numpy() if "f_bb_z" in X.columns else np.zeros(len(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._raw(X) * self._scale)
