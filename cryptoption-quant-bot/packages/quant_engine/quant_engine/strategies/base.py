"""Model/strategy interface.

Every model outputs P(up) — a calibrated probability that the expiry close will
exceed the entry price — and exposes version + schema + training metadata so
each prediction is reproducible and auditable.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class Model(Protocol):
    name: str

    def fit(self, X: pd.DataFrame, y: np.ndarray,
            X_val: pd.DataFrame | None = None,
            y_val: np.ndarray | None = None) -> "Model": ...

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...

    def get_version(self) -> str: ...

    def get_feature_schema(self) -> list[str]: ...

    def get_training_metadata(self) -> dict[str, Any]: ...


def make_model(name: str, *, seed: int = 7, logistic_c: float = 0.1,
               calibration: str = "sigmoid") -> Model:
    from .baselines import MeanReversionBaseline, RandomBaseline, TrendBaseline
    from .logistic import RegularizedLogistic

    if name == "random":
        return RandomBaseline(seed=seed)
    if name == "trend":
        return TrendBaseline()
    if name == "meanrev":
        return MeanReversionBaseline()
    if name == "logistic":
        return RegularizedLogistic(c=logistic_c, calibration=calibration, seed=seed)
    raise ValueError(f"unknown model '{name}'")
