"""
Binary-options backtester.

Model of a PocketOption "higher/lower" trade:
  * A signal is generated on the CLOSE of candle i.
  * You enter at the OPEN of candle i+1 (no look-ahead).
  * The option expires `expiry_candles` candles later; you win if the price
    moved in your predicted direction, measured close-to-entry.
  * Win pays `stake * payout`; loss costs `stake`; exact tie refunds `stake`.

Because entry uses the *next* open and evaluation uses a *future* close, the
backtest never peeks at data the live bot wouldn't have. The one thing it can't
model is broker-side price manipulation on synthetic OTC assets — which is
exactly why you should validate on real (crypto) candles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .data import Candles
from .strategy import ConfluenceStrategy, StrategyConfig
from .risk import RiskManager, RiskConfig


@dataclass
class Trade:
    index: int
    direction: str
    entry: float
    exit: float
    stake: float
    result: str  # "win" | "loss" | "tie"
    pnl: float
    balance_after: float
    confidence: float


@dataclass
class BacktestReport:
    symbol: str
    timeframe: int
    payout: float
    expiry_candles: int
    starting_balance: float
    ending_balance: float
    trades: list[Trade] = field(default_factory=list)
    synthetic_data: bool = False

    @property
    def n_trades(self) -> int:
        return len([t for t in self.trades if t.result != "tie"])

    @property
    def wins(self) -> int:
        return len([t for t in self.trades if t.result == "win"])

    @property
    def losses(self) -> int:
        return len([t for t in self.trades if t.result == "loss"])

    @property
    def win_rate(self) -> float:
        n = self.n_trades
        return (self.wins / n * 100) if n else 0.0

    @property
    def total_pnl(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def roi_pct(self) -> float:
        return (self.total_pnl / self.starting_balance * 100) if self.starting_balance else 0.0

    @property
    def breakeven_win_rate(self) -> float:
        """Directional win-rate needed just to break even at this payout."""
        return 100.0 / (1.0 + self.payout)

    @property
    def edge_pct(self) -> float:
        """Win-rate minus break-even. Positive => the strategy has an edge."""
        return self.win_rate - self.breakeven_win_rate

    @property
    def max_drawdown_pct(self) -> float:
        peak = self.starting_balance
        max_dd = 0.0
        for t in self.trades:
            peak = max(peak, t.balance_after)
            if peak > 0:
                dd = (peak - t.balance_after) / peak * 100
                max_dd = max(max_dd, dd)
        return max_dd

    @property
    def expectancy_per_trade(self) -> float:
        n = self.n_trades
        return (self.total_pnl / n) if n else 0.0


class BinaryBacktester:
    def __init__(
        self,
        candles: Candles,
        strat_cfg: StrategyConfig | None = None,
        risk_cfg: RiskConfig | None = None,
        payout: float = 0.85,
        expiry_candles: int = 1,
    ):
        self.candles = candles
        self.strat_cfg = strat_cfg or StrategyConfig()
        self.risk_cfg = risk_cfg or RiskConfig()
        self.payout = payout
        self.expiry_candles = expiry_candles

    def run(self) -> BacktestReport:
        c = self.candles
        strat = ConfluenceStrategy(c, self.strat_cfg)
        risk = RiskManager(self.risk_cfg)
        trades: list[Trade] = []

        start = strat.ready_from()
        # need room for entry (i+1) and expiry (i+1+expiry)
        end = len(c) - self.expiry_candles - 1

        for i in range(start, end):
            can, _ = risk.can_trade()
            if not can:
                break
            sig = strat.evaluate(i)
            if not sig.is_trade:
                continue

            entry = c.opens[i + 1]
            exit_price = c.closes[i + 1 + self.expiry_candles - 1] if self.expiry_candles > 0 else c.closes[i + 1]
            stake = risk.next_stake()

            if entry == exit_price:
                result, pnl = "tie", 0.0
                risk.record_tie()
            else:
                up = exit_price > entry
                won = (sig.direction == "CALL" and up) or (sig.direction == "PUT" and not up)
                if won:
                    result = "win"
                    pnl = stake * self.payout
                    risk.record_win(stake, self.payout)
                else:
                    result = "loss"
                    pnl = -stake
                    risk.record_loss(stake)

            trades.append(
                Trade(
                    index=i,
                    direction=sig.direction,
                    entry=entry,
                    exit=exit_price,
                    stake=stake,
                    result=result,
                    pnl=round(pnl, 2),
                    balance_after=round(risk.state.balance, 2),
                    confidence=round(sig.confidence, 2),
                )
            )

        return BacktestReport(
            symbol=c.symbol,
            timeframe=c.timeframe,
            payout=self.payout,
            expiry_candles=self.expiry_candles,
            starting_balance=self.risk_cfg.starting_balance,
            ending_balance=round(risk.state.balance, 2),
            trades=trades,
            synthetic_data=c.synthetic,
        )
