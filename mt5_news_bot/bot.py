"""
State machine that arms a straddle around a single news event.

IDLE -> (T - SECONDS_BEFORE_NEWS) -> WAITING -> ORDERS_PLACED
     -> (one leg fills) -> IN_TRADE -> (SL/TP hit) -> IDLE
"""

import time
from datetime import datetime, timezone
from enum import Enum, auto

import config
from mt5_client import MT5Client, MT5ConnectionError
from news_calendar import EconomicEvent


class State(Enum):
    IDLE = auto()
    WAITING = auto()
    ORDERS_PLACED = auto()
    IN_TRADE = auto()


class NewsTradingBot:
    def __init__(self, client: MT5Client, log=print):
        self.client = client
        self.state = State.IDLE
        self.log = log
        self.trades_today = 0
        self.trade_date = None

    def _reset_daily_counter(self):
        today = datetime.now(timezone.utc).date()
        if self.trade_date != today:
            self.trade_date = today
            self.trades_today = 0

    def run_event(self, event: EconomicEvent, symbol: str) -> None:
        self._reset_daily_counter()
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            self.log(f"[SKIP] Daily trade limit ({config.MAX_TRADES_PER_DAY}) reached, skipping {event.name}")
            return

        self.state = State.WAITING
        self.log(f"[WAITING] {event.name} on {symbol} at {event.time_utc.isoformat()}")

        arm_at = event.time_utc.timestamp() - config.SECONDS_BEFORE_NEWS
        self._sleep_until(arm_at)

        spread = self.client.spread_pips(symbol)
        if spread > config.MAX_SPREAD_PIPS:
            self.log(f"[SKIP] Spread {spread:.1f} pips > max {config.MAX_SPREAD_PIPS}, skipping {event.name}")
            self.state = State.IDLE
            return

        try:
            buy, sell = self.client.place_straddle(
                symbol,
                config.LOT_SIZE,
                config.STRADDLE_PIPS,
                config.STOP_LOSS_PIPS,
                config.TAKE_PROFIT_PIPS,
            )
        except MT5ConnectionError as e:
            self.log(f"[ERROR] Failed to place straddle for {event.name}: {e}")
            self.state = State.IDLE
            return

        self.state = State.ORDERS_PLACED
        self.log(f"[ORDERS_PLACED] BUY_STOP #{buy.ticket} @ {buy.price:.5f}, "
                 f"SELL_STOP #{sell.ticket} @ {sell.price:.5f}")

        self._await_fill_or_expire(symbol, buy, sell, event)

    def _await_fill_or_expire(self, symbol, buy, sell, event) -> None:
        deadline = time.time() + config.POST_NEWS_TIMEOUT_SECONDS
        position = None
        while time.time() < deadline:
            position = self.client.get_open_position(symbol)
            if position is not None:
                break
            time.sleep(0.05)

        if position is None:
            self.log(f"[TIMEOUT] Neither leg filled for {event.name}, cancelling both")
            self._safe_cancel(buy.ticket)
            self._safe_cancel(sell.ticket)
            self.state = State.IDLE
            return

        losing_ticket = sell.ticket if position.ticket == buy.ticket else buy.ticket
        self._safe_cancel(losing_ticket)
        self.state = State.IN_TRADE
        self.trades_today += 1
        self.log(f"[IN_TRADE] {position.order_type} filled @ {position.open_price:.5f} "
                 f"(cancelled opposite order #{losing_ticket})")

        self._await_close(position)

    def _safe_cancel(self, ticket: int) -> None:
        try:
            if self.client.has_pending_order(ticket):
                self.client.cancel_order(ticket)
        except MT5ConnectionError as e:
            self.log(f"[WARN] Failed to cancel order #{ticket}: {e}")

    def _await_close(self, position) -> None:
        while not self.client.is_position_closed(position.ticket):
            time.sleep(1)
        self.log(f"[IDLE] Position #{position.ticket} closed (SL/TP)")
        self.state = State.IDLE

    @staticmethod
    def _sleep_until(target_ts: float) -> None:
        remaining = target_ts - time.time()
        if remaining > 0:
            time.sleep(remaining)
