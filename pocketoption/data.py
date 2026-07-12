"""
Candle data.

PocketOption has no official public market-data API, and its OTC assets are
synthetic (broker-generated) so they cannot be backtested against real data.
For honest, reproducible backtesting we pull *real* OHLC candles from Binance's
public klines endpoint (no API key needed) for crypto pairs, which PocketOption
also lists. If the network is unavailable we fall back to a synthetic random
walk so the tooling still runs offline (clearly flagged as synthetic).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

# Multiple public klines endpoints; some are geo-restricted (HTTP 451), so we
# try them in order until one answers. All are keyless.
KLINES_HOSTS = [
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
]

# PocketOption timeframe (seconds) -> Binance interval string
_INTERVAL_MAP = {
    60: "1m",
    300: "5m",
    900: "15m",
    1800: "30m",
    3600: "1h",
}


@dataclass
class Candles:
    """Column-oriented OHLC series."""

    symbol: str
    timeframe: int  # seconds per candle
    times: list[int]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]
    synthetic: bool = False

    def __len__(self) -> int:
        return len(self.closes)


def fetch_candles(
    symbol: str = "BTCUSDT",
    timeframe: int = 60,
    limit: int = 1000,
) -> Candles:
    """Fetch real candles from Binance, falling back to synthetic data."""
    interval = _INTERVAL_MAP.get(timeframe, "1m")
    if httpx is not None:
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        for host in KLINES_HOSTS:
            try:
                resp = httpx.get(host, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                rows = resp.json()
                if not isinstance(rows, list) or not rows:
                    continue
                return Candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    times=[int(r[0]) for r in rows],
                    opens=[float(r[1]) for r in rows],
                    highs=[float(r[2]) for r in rows],
                    lows=[float(r[3]) for r in rows],
                    closes=[float(r[4]) for r in rows],
                    volumes=[float(r[5]) for r in rows],
                )
            except Exception:
                continue  # try next host
    return synthetic_candles(symbol=symbol, timeframe=timeframe, limit=limit)


def synthetic_candles(
    symbol: str = "SYNTH",
    timeframe: int = 60,
    limit: int = 1000,
    seed: int | None = 42,
    start_price: float = 100.0,
    drift: float = 0.0,
    vol: float = 0.0015,
) -> Candles:
    """Generate a reproducible random-walk OHLC series for offline testing."""
    rng = random.Random(seed)
    times, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    price = start_price
    t = 1_600_000_000_000
    for _ in range(limit):
        o = price
        ret = drift + rng.gauss(0, vol)
        c = max(0.01, o * (1 + ret))
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        times.append(t)
        opens.append(o)
        highs.append(hi)
        lows.append(lo)
        closes.append(c)
        volumes.append(rng.uniform(10, 100))
        price = c
        t += timeframe * 1000
    return Candles(
        symbol=symbol,
        timeframe=timeframe,
        times=times,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        synthetic=True,
    )
