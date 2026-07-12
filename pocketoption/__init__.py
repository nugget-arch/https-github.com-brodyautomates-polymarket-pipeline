"""
PocketOption trading bot — a technical-analysis binary-options bot with
realistic backtesting, risk management and paper trading.

IMPORTANT / HONEST DISCLAIMER
-----------------------------
No bot can *guarantee* profit on binary options. Payouts below 100% mean the
game has a negative expectancy unless your directional win-rate clears the
break-even threshold (e.g. an 85% payout needs > 54.05% wins just to break
even). This package gives you the tooling to *measure* whether a strategy has
an edge (backtest), to *protect* your capital when it doesn't (risk manager),
and to *practise* without risking money (paper broker). Use it responsibly and
only trade money you can afford to lose.
"""

from .strategy import Signal, ConfluenceStrategy
from .backtest import BinaryBacktester, BacktestReport
from .risk import RiskManager, RiskConfig
from .broker import PaperBroker
from .config import BotConfig

__all__ = [
    "Signal",
    "ConfluenceStrategy",
    "BinaryBacktester",
    "BacktestReport",
    "RiskManager",
    "RiskConfig",
    "PaperBroker",
    "BotConfig",
]
