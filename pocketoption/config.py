"""
Bot configuration, sourced from environment variables (see .env.example) with
sensible, conservative defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class BotConfig:
    # market
    symbol: str = os.getenv("PO_SYMBOL", "BTCUSDT")
    timeframe: int = _i("PO_TIMEFRAME", 60)           # seconds per candle
    expiry_candles: int = _i("PO_EXPIRY_CANDLES", 1)  # option expiry in candles
    payout: float = _f("PO_PAYOUT", 0.85)             # broker payout fraction

    # strategy
    regime: str = os.getenv("PO_REGIME", "trend")     # "trend" | "reversion"
    min_confidence: float = _f("PO_MIN_CONFIDENCE", 0.6)

    # risk
    starting_balance: float = _f("PO_START_BALANCE", 1000.0)
    stake_fraction: float = _f("PO_STAKE_FRACTION", 0.02)
    daily_loss_limit_pct: float = _f("PO_DAILY_LOSS_PCT", 0.10)
    daily_profit_target_pct: float = _f("PO_DAILY_PROFIT_PCT", 0.20)
    max_consecutive_losses: int = _i("PO_MAX_LOSSES", 4)
    martingale: bool = _b("PO_MARTINGALE", False)

    # execution
    live: bool = _b("PO_LIVE", False)                 # False => paper trading
    poll_seconds: int = _i("PO_POLL_SECONDS", 5)
    pocketoption_ssid: str = os.getenv("POCKETOPTION_SSID", "")
