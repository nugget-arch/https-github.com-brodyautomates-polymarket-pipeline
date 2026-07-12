"""Optional LightGBM strategy. Imported only when strategies.use_lightgbm.

Deliberately gated: gradient boosting overfits noise with ease, so it should
only enter the comparison once simple models have been evaluated. Neural
networks are intentionally absent until simple models demonstrate an
out-of-sample edge (see project policy in the README).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError as _e:  # pragma: no cover
    lgb = None
    _IMPORT_ERROR = _e

from .logistic import _PlattScaler


class LightGBMStrategy:
    name = "lightgbm"

    def __init__(self, params: dict, calibration: str = "sigmoid", seed: int = 7):
        if lgb is None:  # pragma: no cover
            raise ImportError(
                "lightgbm is not installed; `pip install otc-lab[lgbm]`"
            ) from _IMPORT_ERROR
        self.params = {**params, "random_state": seed, "verbosity": -1,
                       "objective": "binary"}
        self.calibration = calibration
        self._model: "lgb.LGBMClassifier | None" = None
        self._cal: _PlattScaler | None = None

    def fit(self, X: pd.DataFrame, y: np.ndarray,
            X_val: pd.DataFrame | None = None, y_val: np.ndarray | None = None):
        self._model = lgb.LGBMClassifier(**self.params)
        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None
        self._model.fit(
            X, y, eval_set=eval_set,
            callbacks=[lgb.early_stopping(50, verbose=False)] if eval_set else None,
        )
        self._cal = None
        if self.calibration != "none" and X_val is not None and y_val is not None and len(X_val) > 50:
            p_val = self._model.predict_proba(X_val)[:, 1]
            self._cal = _PlattScaler().fit(p_val, np.asarray(y_val))
        return self

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("fit() before predict")
        p = self._model.predict_proba(X)[:, 1]
        if self._cal is not None:
            p = self._cal.transform(p)
        return np.clip(p, 1e-6, 1 - 1e-6)
