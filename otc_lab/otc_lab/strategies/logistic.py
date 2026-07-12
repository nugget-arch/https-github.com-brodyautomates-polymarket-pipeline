"""Regularised logistic regression with probability calibration.

Calibration is fitted on the *validation* slice (never train, never test):
sigmoid (Platt) by default, isotonic when the validation fold is large enough
for it not to overfit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_MIN_ISOTONIC_N = 500


class _PlattScaler:
    """1-D logistic fit p_cal = sigmoid(a * logit(p) + b)."""

    def __init__(self) -> None:
        self._lr = LogisticRegression(C=1e6, solver="lbfgs")

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def fit(self, p: np.ndarray, y: np.ndarray) -> "_PlattScaler":
        self._lr.fit(self._logit(p).reshape(-1, 1), y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return self._lr.predict_proba(self._logit(p).reshape(-1, 1))[:, 1]


class LogisticStrategy:
    name = "logistic"

    def __init__(self, c: float = 0.1, calibration: str = "sigmoid", seed: int = 7):
        self.c = c
        self.calibration = calibration
        self.seed = seed
        self._pipe: Pipeline | None = None
        self._cal: _PlattScaler | IsotonicRegression | None = None

    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        X_val: pd.DataFrame | None = None,
        y_val: np.ndarray | None = None,
    ) -> "LogisticStrategy":
        self._pipe = Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(
                C=self.c, solver="lbfgs",  # default penalty is L2
                max_iter=2000, random_state=self.seed,
            )),
        ])
        self._pipe.fit(X.to_numpy(), y)

        self._cal = None
        if self.calibration != "none" and X_val is not None and y_val is not None and len(X_val) > 50:
            p_val = self._pipe.predict_proba(X_val.to_numpy())[:, 1]
            if self.calibration == "isotonic" and len(X_val) >= _MIN_ISOTONIC_N:
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                iso.fit(p_val, y_val)
                self._cal = iso
            else:
                self._cal = _PlattScaler().fit(p_val, y_val)
        return self

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        if self._pipe is None:
            raise RuntimeError("fit() before predict")
        p = self._pipe.predict_proba(X.to_numpy())[:, 1]
        if self._cal is not None:
            p = (
                self._cal.transform(p)
                if isinstance(self._cal, _PlattScaler)
                else self._cal.predict(p)
            )
        return np.clip(p, 1e-6, 1 - 1e-6)
