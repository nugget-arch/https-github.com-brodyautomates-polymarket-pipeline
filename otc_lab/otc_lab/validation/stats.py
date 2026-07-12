"""Statistical machinery: CIs, bootstrap, hypothesis tests, multiplicity.

Everything here is deliberately conservative. When in doubt the platform must
err toward "no edge demonstrated".
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
    n_boot: int
    block_size: int


def wilson_ci(wins: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (better than normal
    approximation at the sample sizes we care about)."""
    if n == 0:
        return 0.0, 1.0
    z = stats.norm.ppf(0.5 + confidence / 2)
    phat = wins / n
    denom = 1 + z**2 / n
    centre = (phat + z**2 / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def block_bootstrap_ci(
    values: np.ndarray,
    stat: str = "mean",
    n_boot: int = 2000,
    block_size: int = 50,
    confidence: float = 0.95,
    seed: int = 7,
) -> BootstrapCI:
    """Circular block bootstrap CI for the mean (or win-rate when values are
    0/1). Blocks preserve serial correlation that i.i.d. bootstrap destroys."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return BootstrapCI(float("nan"), float("nan"), float("nan"), confidence, n_boot, block_size)
    point = float(values.mean())
    if n < block_size * 2:
        block_size = max(1, n // 4)

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block_size)[None, :]).ravel() % n
        sample = values[idx[:n]]
        boots[b] = sample.mean()
    alpha = 1 - confidence
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return BootstrapCI(point, float(lo), float(hi), confidence, n_boot, block_size)


def binomial_pvalue_vs_breakeven(wins: int, n: int, break_even: float) -> float:
    """One-sided exact binomial test: H0 win_rate <= break_even."""
    if n == 0:
        return 1.0
    return float(stats.binomtest(wins, n, break_even, alternative="greater").pvalue)


def multiple_test_correction(
    pvalues: list[float], method: str = "benjamini_hochberg", alpha: float = 0.05
) -> list[bool]:
    """Return reject/accept per hypothesis controlling for multiplicity.

    When many strategy/expiry/asset combinations are compared, some WILL look
    profitable by luck alone; this is the correction that keeps us honest.
    """
    m = len(pvalues)
    if m == 0:
        return []
    p = np.asarray(pvalues)
    if method == "bonferroni":
        return list(p < alpha / m)
    # Benjamini-Hochberg
    order = np.argsort(p)
    ranked = p[order]
    thresh = alpha * (np.arange(1, m + 1) / m)
    passed = ranked <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
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
    """Reliability diagram data: predicted vs observed frequency per bin."""
    p = np.asarray(p_up)
    y = np.asarray(y_up)
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        mask = (p >= edges[i]) & (p < edges[i + 1] if i < n_bins - 1 else p <= edges[i + 1])
        if mask.sum() == 0:
            continue
        rows.append({
            "bin_lo": float(edges[i]),
            "bin_hi": float(edges[i + 1]),
            "n": int(mask.sum()),
            "p_mean": float(p[mask].mean()),
            "y_rate": float(y[mask].mean()),
        })
    return rows
