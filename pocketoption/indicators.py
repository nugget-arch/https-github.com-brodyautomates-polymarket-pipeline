"""
Pure-Python technical indicators (no numpy dependency, so the bot runs
anywhere). All functions take a list[float] of closes (or OHLC) and return a
list aligned to the input length, with `None` for the warm-up period where the
indicator is not yet defined.
"""
from __future__ import annotations

from typing import Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    # seed with SMA of the first `period` values
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        gain = max(ch, 0.0)
        loss = max(-ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    # signal line = EMA of the defined part of macd_line
    defined = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    sig_line: list[float | None] = [None] * len(values)
    if len(defined) >= signal:
        vals = [v for _, v in defined]
        sig_vals = ema(vals, signal)
        for (idx, _), sv in zip(defined, sig_vals):
            sig_line[idx] = sv
    hist: list[float | None] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, sig_line)
    ]
    return macd_line, sig_line, hist


def bollinger(
    values: Sequence[float], period: int = 20, mult: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (upper, middle, lower) bands."""
    mid = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if i >= period - 1 and mid[i] is not None:
            window = values[i - period + 1 : i + 1]
            m = mid[i]
            var = sum((x - m) ** 2 for x in window) / period
            sd = var**0.5
            upper[i] = m + mult * sd
            lower[i] = m - mult * sd
    return upper, mid, lower


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    n = len(closes)
    trs: list[float] = [0.0] * n
    for i in range(n):
        if i == 0:
            trs[i] = highs[i] - lows[i]
        else:
            trs[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
    return ema(trs, period)


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    """Returns (%K, %D)."""
    n = len(closes)
    k: list[float | None] = [None] * n
    for i in range(n):
        if i >= k_period - 1:
            hh = max(highs[i - k_period + 1 : i + 1])
            ll = min(lows[i - k_period + 1 : i + 1])
            k[i] = 100.0 * (closes[i] - ll) / (hh - ll) if hh != ll else 50.0
    defined = [(i, v) for i, v in enumerate(k) if v is not None]
    d: list[float | None] = [None] * n
    if len(defined) >= d_period:
        vals = [v for _, v in defined]
        d_vals = sma(vals, d_period)
        for (idx, _), dv in zip(defined, d_vals):
            d[idx] = dv
    return k, d
