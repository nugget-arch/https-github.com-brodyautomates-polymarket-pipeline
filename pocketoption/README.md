# PocketOption Trading Bot

A technical-analysis binary-options bot with **realistic backtesting**, strict
**risk management**, and **paper trading** on real market data.

> ### ⚠️ Read this first — honest expectations
> No bot can *guarantee* profit on binary options. When the payout is below
> 100%, the game has **negative expectancy** unless your directional win-rate
> clears the break-even line. At an 85% payout you need to win **> 54.05%** of
> trades *just to break even*. Anyone selling you a "100% profitable" bot is
> lying.
>
> What this project actually gives you:
> 1. A way to **measure** whether a strategy has an edge (backtest + walk-forward).
> 2. Guards to **protect** your capital when it doesn't (risk manager).
> 3. A **paper broker** so you can practise with zero money at risk.
>
> Trade only money you can afford to lose. This is educational software, not
> financial advice.

## Why backtest on Binance data?

PocketOption has no official public market-data API, and its **OTC assets are
synthetic** (broker-generated), so they can't be validated against reality. For
honest backtesting we pull *real* OHLC candles from public Binance endpoints for
crypto pairs that PocketOption also lists (BTCUSDT, ETHUSDT, …). If every
endpoint is blocked (some are geo-restricted), the bot falls back to a clearly
flagged synthetic random walk so the tooling still runs offline.

## Install

```bash
pip install -r requirements.txt   # httpx, python-dotenv, rich (already in repo)
```

The core (indicators, strategy, backtester, risk) is **pure Python** — no numpy
required.

## Usage

Backtest one configuration:

```bash
python -m pocketoption.cli backtest --symbol BTCUSDT --tf 300 --regime reversion --expiry 2
```

Walk-forward grid search (optimises on the first 70% of candles, then reports the
best config on the **held-out** 30% — this is how you catch overfitting):

```bash
python -m pocketoption.cli optimize --symbol ETHUSDT --tf 300
```

Paper-trade live data (no money at risk):

```bash
python -m pocketoption.cli paper --symbol BTCUSDT --tf 60 --max-trades 20
```

## How the pieces fit

| Module          | Responsibility                                             |
|-----------------|------------------------------------------------------------|
| `indicators.py` | Pure-Python EMA, RSI, MACD, Bollinger, ATR, Stochastic     |
| `strategy.py`   | Confluence strategy → `Signal(CALL/PUT/NONE, confidence)`  |
| `data.py`       | Real candles (Binance) with synthetic offline fallback     |
| `risk.py`       | Position sizing + daily/streak guards (+ optional capped martingale) |
| `backtest.py`   | Binary-options backtester (no look-ahead) + edge metrics   |
| `broker.py`     | `PaperBroker` (simulated) + `PocketOptionBroker` stub       |
| `bot.py`        | Live/paper loop wiring strategy + risk + broker            |
| `cli.py`        | `backtest` / `optimize` / `paper` commands                 |

## The strategy

A **confluence** model: it only fires when several independent indicators agree,
which raises the directional win-rate at the cost of trading less often. Two
regimes:

- **trend** — trade with the EMA trend on momentum pushes.
- **reversion** — fade stretched moves back to the mean (Bollinger + RSI/Stoch).

A volatility gate (ATR/price) skips dead or chaotic markets. Confidence is the
fraction of conditions that align; `min_confidence` sets the firing threshold.

This is a **tunable template, not a money printer.** Whether it has an edge on a
given asset/timeframe is an empirical question — run the backtester and let the
numbers decide.

## Risk management (the part you can actually control)

- Fixed-fraction (default 2%/trade) or fixed-amount position sizing.
- **Daily loss limit** — stops the session after losing X% of balance.
- **Daily profit target** — locks in a good day.
- **Max consecutive losses** — forced cool-off.
- **Martingale** is available but **OFF by default and capped**. It does *not*
  improve expectancy; it swaps a high hit-rate for rare catastrophic ruin. Leave
  it off.

## Going live (deliberately not done for you)

`PocketOptionBroker` is an intentional stub. A real integration relies on an
**unofficial** API library or browser automation, which may **violate
PocketOption's terms** and break without notice. If you choose to implement it:

1. Implement `PocketOptionBroker` against a library you trust.
2. Keep `demo=True` (PocketOption demo account) until you've validated it live.
3. Only then, consciously, consider real funds — starting tiny.

## Workflow we recommend

```
optimize  ->  backtest the winner on a different symbol/period  ->  paper-trade
          ->  demo account  ->  (only if a real edge persists) small real size
```

If the edge disappears out-of-sample or in paper trading, **that is the tool
working correctly.** Better to learn it here than with your money.
