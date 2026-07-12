"""
Live/paper trading loop.

By default the bot runs in PAPER mode against real candle data: it computes the
strategy on the latest candles, places simulated trades through `PaperBroker`,
and enforces every risk guard. Set `live=True` (env PO_LIVE=true) only after you
have (a) validated an edge in backtesting and (b) implemented `PocketOptionBroker`
against a broker connection you trust.
"""
from __future__ import annotations

import time

from .config import BotConfig
from .data import fetch_candles
from .strategy import ConfluenceStrategy, StrategyConfig
from .risk import RiskManager, RiskConfig
from .broker import PaperBroker, PocketOptionBroker


class TradingBot:
    def __init__(self, cfg: BotConfig | None = None):
        self.cfg = cfg or BotConfig()
        self.risk = RiskManager(
            RiskConfig(
                starting_balance=self.cfg.starting_balance,
                stake_fraction=self.cfg.stake_fraction,
                daily_loss_limit_pct=self.cfg.daily_loss_limit_pct,
                daily_profit_target_pct=self.cfg.daily_profit_target_pct,
                max_consecutive_losses=self.cfg.max_consecutive_losses,
                martingale=self.cfg.martingale,
            )
        )
        self.strat_cfg = StrategyConfig(
            regime=self.cfg.regime, min_confidence=self.cfg.min_confidence
        )
        if self.cfg.live:
            self.broker = PocketOptionBroker(
                ssid=self.cfg.pocketoption_ssid, demo=True
            )
        else:
            self.broker = PaperBroker(
                price_fn=self._last_price,
                balance=self.cfg.starting_balance,
                payout=self.cfg.payout,
            )

    def _last_price(self, symbol: str) -> float:
        candles = fetch_candles(symbol, self.cfg.timeframe, limit=2)
        return candles.closes[-1]

    def _current_signal(self):
        candles = fetch_candles(
            self.cfg.symbol, self.cfg.timeframe, limit=200
        )
        strat = ConfluenceStrategy(candles, self.strat_cfg)
        return candles, strat.evaluate(len(candles) - 1)

    def run(self, max_trades: int | None = None, log=print) -> None:
        mode = "LIVE" if self.cfg.live else "PAPER"
        log(f"[{mode}] Starting bot on {self.cfg.symbol} "
            f"{self.cfg.timeframe}s / expiry {self.cfg.expiry_candles} candle(s)")
        log(f"Break-even win-rate at {self.cfg.payout:.0%} payout: "
            f"{100/(1+self.cfg.payout):.2f}%  — you must beat this to profit.")

        placed = 0
        while True:
            can, reason = self.risk.can_trade()
            if not can:
                log(f"Halted: {reason}. Final balance {self.risk.state.balance:.2f}")
                break
            if max_trades is not None and placed >= max_trades:
                log(f"Reached max_trades={max_trades}. Balance {self.risk.state.balance:.2f}")
                break

            try:
                candles, sig = self._current_signal()
            except Exception as e:  # network hiccup etc.
                log(f"data error: {e}; retrying in {self.cfg.poll_seconds}s")
                time.sleep(self.cfg.poll_seconds)
                continue

            if not sig.is_trade:
                time.sleep(self.cfg.poll_seconds)
                continue

            stake = self.risk.next_stake()
            expiry_s = self.cfg.timeframe * self.cfg.expiry_candles
            pos = self.broker.place(self.cfg.symbol, sig.direction, stake, expiry_s)
            log(f"OPEN {sig.direction} stake={stake:.2f} @ {pos.entry_price} "
                f"conf={sig.confidence:.2f} :: {', '.join(sig.reasons)}")

            # wait for expiry, then settle
            time.sleep(expiry_s)
            outcome = self.broker.settle(pos)
            if outcome.tie:
                self.risk.record_tie()
                log(f"TIE refund. balance {self.risk.state.balance:.2f}")
            elif outcome.won:
                self.risk.record_win(stake, self.cfg.payout)
                log(f"WIN +{stake*self.cfg.payout:.2f}. balance {self.risk.state.balance:.2f}")
            else:
                self.risk.record_loss(stake)
                log(f"LOSS -{stake:.2f}. balance {self.risk.state.balance:.2f}")
            placed += 1
