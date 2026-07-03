"""
Thin wrapper around the MetaTrader5 terminal API.

The `MetaTrader5` package only works against a running MT5 terminal, which
in turn only runs on Windows (or Wine). When it isn't installed/available
— e.g. when developing on Linux/Mac — this module falls back to a
DRY_RUN simulator so the rest of the bot can still be exercised end to end.
"""

import random
import time
from dataclasses import dataclass

import config

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

ORDER_TYPE_BUY_STOP = "BUY_STOP"
ORDER_TYPE_SELL_STOP = "SELL_STOP"


@dataclass
class Quote:
    bid: float
    ask: float

    @property
    def spread_points(self) -> float:
        return self.ask - self.bid


@dataclass
class PendingOrder:
    ticket: int
    symbol: str
    order_type: str
    price: float
    sl: float
    tp: float
    volume: float


@dataclass
class Position:
    ticket: int
    symbol: str
    order_type: str
    open_price: float
    sl: float
    tp: float
    volume: float


class MT5ConnectionError(RuntimeError):
    pass


def _pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


class MT5Client:
    """Live client when MetaTrader5 is installed and DRY_RUN is false;
    otherwise a deterministic-ish simulator for local testing."""

    def __init__(self):
        self.simulated = config.DRY_RUN or not MT5_AVAILABLE
        self._sim_price = {"EURUSD": 1.0850, "GBPUSD": 1.2650, "USDJPY": 155.00}
        self._sim_orders: dict[int, PendingOrder] = {}
        self._sim_positions: dict[int, Position] = {}
        self._sim_ticket_seq = 1000

    def connect(self) -> None:
        if self.simulated:
            return
        if not mt5.initialize(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
            path=config.MT5_TERMINAL_PATH or None,
        ):
            raise MT5ConnectionError(f"MT5 initialize() failed: {mt5.last_error()}")

    def shutdown(self) -> None:
        if not self.simulated:
            mt5.shutdown()

    def get_quote(self, symbol: str) -> Quote:
        if self.simulated:
            mid = self._sim_price.setdefault(symbol, 1.0)
            spread = _pip_size(symbol) * random.uniform(0.5, 2.5)
            return Quote(bid=mid - spread / 2, ask=mid + spread / 2)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5ConnectionError(f"No tick data for {symbol}")
        return Quote(bid=tick.bid, ask=tick.ask)

    def spread_pips(self, symbol: str) -> float:
        q = self.get_quote(symbol)
        return q.spread_points / _pip_size(symbol)

    def place_straddle(
        self, symbol: str, volume: float, straddle_pips: float, sl_pips: float, tp_pips: float
    ) -> tuple[PendingOrder, PendingOrder]:
        """Place a BUY_STOP above and a SELL_STOP below the current price."""
        pip = _pip_size(symbol)
        quote = self.get_quote(symbol)
        mid = (quote.bid + quote.ask) / 2

        buy_price = mid + straddle_pips * pip
        sell_price = mid - straddle_pips * pip

        buy = self._send_pending(symbol, ORDER_TYPE_BUY_STOP, buy_price, volume,
                                   sl=buy_price - sl_pips * pip, tp=buy_price + tp_pips * pip)
        sell = self._send_pending(symbol, ORDER_TYPE_SELL_STOP, sell_price, volume,
                                    sl=sell_price + sl_pips * pip, tp=sell_price - tp_pips * pip)
        return buy, sell

    def _send_pending(self, symbol, order_type, price, volume, sl, tp) -> PendingOrder:
        if self.simulated:
            ticket = self._sim_ticket_seq
            self._sim_ticket_seq += 1
            order = PendingOrder(ticket, symbol, order_type, price, sl, tp, volume)
            self._sim_orders[ticket] = order
            return order

        mt5_order_type = mt5.ORDER_TYPE_BUY_STOP if order_type == ORDER_TYPE_BUY_STOP else mt5.ORDER_TYPE_SELL_STOP
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": int(time.time()) + int(config.ORDER_EXPIRY_SECONDS),
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5ConnectionError(f"order_send failed: {result.retcode} {result.comment}")
        return PendingOrder(result.order, symbol, order_type, price, sl, tp, volume)

    def cancel_order(self, ticket: int) -> None:
        if self.simulated:
            self._sim_orders.pop(ticket, None)
            return
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5ConnectionError(f"cancel failed: {result.retcode} {result.comment}")

    def get_open_position(self, symbol: str) -> Position | None:
        """Returns the open position for symbol if one of the straddle legs
        has triggered, else None."""
        if self.simulated:
            for pos in self._sim_positions.values():
                if pos.symbol == symbol:
                    return pos
            return self._sim_check_fill(symbol)

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return None
        p = positions[0]
        order_type = ORDER_TYPE_BUY_STOP if p.type == mt5.ORDER_TYPE_BUY else ORDER_TYPE_SELL_STOP
        return Position(p.ticket, p.symbol, order_type, p.price_open, p.sl, p.tp, p.volume)

    def _sim_check_fill(self, symbol: str) -> Position | None:
        """Simulates a news spike: randomly triggers one pending leg."""
        pending = [o for o in self._sim_orders.values() if o.symbol == symbol]
        if not pending:
            return None
        if random.random() > 0.3:
            return None
        chosen = random.choice(pending)
        self._sim_price[symbol] = chosen.price
        pos = Position(chosen.ticket, chosen.symbol, chosen.order_type, chosen.price, chosen.sl, chosen.tp, chosen.volume)
        self._sim_positions[chosen.ticket] = pos
        for o in pending:
            self._sim_orders.pop(o.ticket, None)
        return pos

    def has_pending_order(self, ticket: int) -> bool:
        if self.simulated:
            return ticket in self._sim_orders
        orders = mt5.orders_get(ticket=ticket)
        return bool(orders)

    def is_position_closed(self, ticket: int) -> bool:
        if self.simulated:
            if ticket not in self._sim_positions:
                return True
            if random.random() < 0.2:
                self._sim_positions.pop(ticket, None)
                return True
            return False
        return mt5.positions_get(ticket=ticket) in (None, ())
