"""Core statistical helpers (CIs, bootstrap, tests, calibration).

Deliberately conservative: when in doubt, err toward "no edge". Phase 5 builds
walk-forward / purge / embargo / Benjamini-Hochberg on top of these.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class BootstrapCI:
    point: float
    lo: float
    hi: float
    confidence: float


def wilson_ci(wins: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z = stats.norm.ppf(0.5 + confidence / 2)
    phat = wins / n
    denom = 1 + z**2 / n
    centre = (phat + z**2 / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def block_bootstrap_ci(values: np.ndarray, n_boot: int = 2000, block_size: int = 50,
                       confidence: float = 0.95, seed: int = 7) -> BootstrapCI:
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return BootstrapCI(float("nan"), float("nan"), float("nan"), confidence)
    point = float(values.mean())
    if n < block_size * 2:
        block_size = max(1, n // 4)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block_size)[None, :]).ravel() % n
        boots[b] = values[idx[:n]].mean()
    alpha = 1 - confidence
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return BootstrapCI(point, float(lo), float(hi), confidence)


def binomial_pvalue_vs_breakeven(wins: int, n: int, break_even: float) -> float:
    if n == 0:
        return 1.0
    return float(stats.binomtest(wins, n, break_even, alternative="greater").pvalue)


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    m = len(pvalues)
    if m == 0:
        return []
    p = np.asarray(pvalues)
    order = np.argsort(p)
    ranked = p[order]
    passed = ranked <= alpha * (np.arange(1, m + 1) / m)
    k = int(np.max(np.nonzero(passed)[0]) + 1) if passed.any() else 0
    reject = np.zeros(m, dtype=bool)
    reject[order[:k]] = True
    return list(reject)


def brier_score(p_up: np.ndarray, y_up: np.ndarray) -> float:
    return float(np.mean((np.asarray(p_up) - np.asarray(y_up)) ** 2))


def log_loss_score(p_up: np.ndarray, y_up: np.ndarray) -> float:
    p = np.clip(np.asarray(p_up, dtype=float), 1e-9, 1 - 1e-9)
    y = np.asarray(y_up, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p_up: np.ndarray, y_up: np.ndarray, n_bins: int = 10) -> list[dict]:
    p, y = np.asarray(p_up), np.asarray(y_up)
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        hi_incl = i == n_bins - 1
        mask = (p >= edges[i]) & (p <= edges[i + 1] if hi_incl else p < edges[i + 1])
        if mask.sum() == 0:
            continue
        rows.append({"bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]),
                     "n": int(mask.sum()), "p_mean": float(p[mask].mean()),
                     "y_rate": float(y[mask].mean())})
    return rows


def expected_calibration_error(p_up: np.ndarray, y_up: np.ndarray, n_bins: int = 10) -> float:
    """Weighted average |confidence - accuracy| across probability bins."""
    table = calibration_table(p_up, y_up, n_bins)
    n = len(np.asarray(p_up))
    if n == 0 or not table:
        return float("nan")
    return float(sum(r["n"] / n * abs(r["p_mean"] - r["y_rate"]) for r in table))
