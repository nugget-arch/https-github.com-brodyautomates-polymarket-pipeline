"""
Command line interface for the PocketOption bot.

  python -m pocketoption.cli backtest --symbol BTCUSDT --tf 60 --regime trend
  python -m pocketoption.cli optimize --symbol ETHUSDT --tf 300
  python -m pocketoption.cli paper --symbol BTCUSDT --max-trades 20

Backtesting first is not optional — it is the only honest way to know whether a
configuration has an edge before you risk anything.
"""
from __future__ import annotations

import argparse
import itertools

from .data import fetch_candles
from .strategy import StrategyConfig
from .risk import RiskConfig
from .backtest import BinaryBacktester, BacktestReport
from .config import BotConfig
from .bot import TradingBot

try:
    from rich.console import Console
    from rich.table import Table

    _console = Console()

    def _p(*a, **k):
        _console.print(*a, **k)
except Exception:  # plain fallback
    _console = None

    def _p(*a, **k):
        print(*[str(x) for x in a])


def _print_report(r: BacktestReport) -> None:
    tag = " [SYNTHETIC DATA — offline fallback]" if r.synthetic_data else ""
    edge_ok = r.edge_pct > 0
    lines = [
        f"Symbol / TF      : {r.symbol} / {r.timeframe}s{tag}",
        f"Payout / Expiry  : {r.payout:.0%} / {r.expiry_candles} candle(s)",
        f"Trades           : {r.n_trades}  (W {r.wins} / L {r.losses})",
        f"Win rate         : {r.win_rate:.2f}%",
        f"Break-even needed: {r.breakeven_win_rate:.2f}%",
        f"Edge             : {r.edge_pct:+.2f} pts  -> {'EDGE ✅' if edge_ok else 'NO EDGE ❌'}",
        f"Start -> End bal : {r.starting_balance:.2f} -> {r.ending_balance:.2f}",
        f"ROI              : {r.roi_pct:+.2f}%",
        f"Max drawdown     : {r.max_drawdown_pct:.2f}%",
        f"Expectancy/trade : {r.expectancy_per_trade:+.4f}",
    ]
    if _console:
        from rich.panel import Panel

        style = "green" if edge_ok else "red"
        _console.print(Panel("\n".join(lines), title="Backtest Report", border_style=style))
    else:
        _p("\n=== Backtest Report ===")
        for ln in lines:
            _p(ln)
    if not edge_ok:
        _p("\n[!] This config did NOT beat the break-even win-rate. Do not trade it "
           "with real money. Try another regime/timeframe/symbol or accept there is "
           "no edge here.")


def cmd_backtest(args) -> None:
    candles = fetch_candles(args.symbol, args.tf, limit=args.limit)
    bt = BinaryBacktester(
        candles,
        strat_cfg=StrategyConfig(regime=args.regime, min_confidence=args.min_conf),
        risk_cfg=RiskConfig(starting_balance=args.balance, stake_fraction=args.stake),
        payout=args.payout,
        expiry_candles=args.expiry,
    )
    _print_report(bt.run())


def cmd_optimize(args) -> None:
    """Grid-search regimes / confidence / expiry and rank by edge (walk-forward
    split: optimize on the first 70%, report the best on the held-out 30%)."""
    candles = fetch_candles(args.symbol, args.tf, limit=args.limit)
    split = int(len(candles) * 0.7)

    def slice_candles(c, lo, hi):
        from .data import Candles

        return Candles(
            c.symbol, c.timeframe, c.times[lo:hi], c.opens[lo:hi], c.highs[lo:hi],
            c.lows[lo:hi], c.closes[lo:hi], c.volumes[lo:hi], c.synthetic,
        )

    train = slice_candles(candles, 0, split)
    test = slice_candles(candles, split, len(candles))

    regimes = ["trend", "reversion"]
    confs = [0.5, 0.6, 0.75, 1.0]
    expiries = [1, 2, 3]

    results = []
    for regime, conf, expiry in itertools.product(regimes, confs, expiries):
        bt = BinaryBacktester(
            train,
            strat_cfg=StrategyConfig(regime=regime, min_confidence=conf),
            risk_cfg=RiskConfig(starting_balance=args.balance),
            payout=args.payout,
            expiry_candles=expiry,
        )
        r = bt.run()
        if r.n_trades >= 15:  # ignore over-fit low-sample configs
            results.append(((regime, conf, expiry), r))

    if not results:
        _p("No configuration produced enough trades to evaluate. "
           "Loosen min-confidence or fetch more candles (--limit).")
        return

    results.sort(key=lambda x: x[1].edge_pct, reverse=True)

    if _console:
        t = Table(title=f"In-sample grid search ({args.symbol} {args.tf}s)")
        for col in ("Regime", "MinConf", "Expiry", "Trades", "Win%", "Edge", "ROI%"):
            t.add_column(col, justify="right")
        for (regime, conf, expiry), r in results[:10]:
            t.add_row(regime, f"{conf:.2f}", str(expiry), str(r.n_trades),
                      f"{r.win_rate:.1f}", f"{r.edge_pct:+.1f}", f"{r.roi_pct:+.1f}")
        _console.print(t)
    else:
        _p("Regime  Conf  Exp  Trades  Win%   Edge   ROI%")
        for (regime, conf, expiry), r in results[:10]:
            _p(f"{regime:9s} {conf:.2f} {expiry}  {r.n_trades:5d}  {r.win_rate:5.1f}  {r.edge_pct:+5.1f}  {r.roi_pct:+6.1f}")

    best_cfg = results[0][0]
    _p(f"\nBest in-sample: regime={best_cfg[0]} min_conf={best_cfg[1]} expiry={best_cfg[2]}")
    _p("Validating best config on HELD-OUT data (walk-forward):")
    bt = BinaryBacktester(
        test,
        strat_cfg=StrategyConfig(regime=best_cfg[0], min_confidence=best_cfg[1]),
        risk_cfg=RiskConfig(starting_balance=args.balance),
        payout=args.payout,
        expiry_candles=best_cfg[2],
    )
    _print_report(bt.run())


def cmd_paper(args) -> None:
    cfg = BotConfig(symbol=args.symbol, timeframe=args.tf, payout=args.payout, live=False)
    TradingBot(cfg).run(max_trades=args.max_trades, log=_p)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="PocketOption technical-analysis bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--symbol", default="BTCUSDT")
        sp.add_argument("--tf", type=int, default=60, help="timeframe seconds")
        sp.add_argument("--payout", type=float, default=0.85)
        sp.add_argument("--balance", type=float, default=1000.0)
        sp.add_argument("--limit", type=int, default=1000)

    bt = sub.add_parser("backtest", help="backtest one configuration")
    common(bt)
    bt.add_argument("--regime", choices=["trend", "reversion"], default="trend")
    bt.add_argument("--min-conf", type=float, default=0.6, dest="min_conf")
    bt.add_argument("--expiry", type=int, default=1)
    bt.add_argument("--stake", type=float, default=0.02)
    bt.set_defaults(func=cmd_backtest)

    op = sub.add_parser("optimize", help="walk-forward grid search")
    common(op)
    op.set_defaults(func=cmd_optimize)

    pa = sub.add_parser("paper", help="paper-trade live data (no money at risk)")
    common(pa)
    pa.add_argument("--max-trades", type=int, default=10, dest="max_trades")
    pa.set_defaults(func=cmd_paper)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
