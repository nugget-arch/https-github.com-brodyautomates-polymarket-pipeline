"""Strategy interface.

A strategy maps a feature matrix to P(up) — a probability that the expiry
close will be above the entry price. It must be *calibrated*: downstream
threshold logic assumes probabilities mean what they say. Calibration quality
is measured (Brier, log-loss, reliability curve), not assumed.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from ..config import StrategyConfig


@runtime_checkable
class Strategy(Protocol):
    name: str

    def fit(self, X: pd.DataFrame, y: np.ndarray, X_val: pd.DataFrame | None = None,
            y_val: np.ndarray | None = None) -> "Strategy": ...

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray: ...


def make_strategy(name: str, cfg: StrategyConfig, seed: int) -> Strategy:
    from .baselines import MeanReversionBaseline, RandomBaseline, TrendBaseline
    from .logistic import LogisticStrategy

    if name == "random":
        return RandomBaseline(seed=seed)
    if name == "trend":
        return TrendBaseline()
    if name == "meanrev":
        return MeanReversionBaseline()
    if name == "logistic":
        return LogisticStrategy(c=cfg.logistic_c, calibration=cfg.calibration, seed=seed)
    if name == "lightgbm":
        from .lgbm import LightGBMStrategy  # optional import

        return LightGBMStrategy(params=cfg.lgbm_params, calibration=cfg.calibration, seed=seed)
    raise ValueError(f"unknown strategy '{name}'")
