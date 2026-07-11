#!/usr/bin/env python3
"""
Options Strategy Analyzer — engine.

Fetches real delayed options chains from CBOE (no API key required),
generates thousands of candidate strategies per underlying (singles,
verticals, straddles/strangles, iron condors, covered calls, CSPs) and
computes probabilistic statistics for each one:

- Expected value at expiry (numerical integration over a lognormal
  terminal-price distribution parameterized by each contract's implied vol)
- Probability of profit (POP)
- Max profit / max loss / breakevens / return on capital
- Net greeks (delta, gamma, theta, vega) aggregated from real per-contract greeks

Entry prices are mid-market; every input (bid, ask, IV, greeks, open
interest) comes from the live CBOE feed.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import httpx
import numpy as np

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "AMD", "SPY", "QQQ"]

# Universe constraints
MIN_DTE = 7           # days to expiration
MAX_DTE = 120
STRIKE_BAND = 0.25    # only strikes within ±25% of spot
MAX_SPREAD_PCT = 0.60 # discard contracts whose bid/ask spread is >60% of mid
GRID_POINTS = 240     # integration grid resolution

OCC_RE = re.compile(r"^([A-Z^]+)(\d{6})([CP])(\d{8})$")

STRATEGY_FAMILIES = [
    "long_call", "long_put", "covered_call", "csp",
    "debit_spread", "credit_spread", "straddle_strangle", "iron_condor",
]


@dataclass
class Contract:
    symbol: str
    expiry: str          # YYYY-MM-DD
    dte: float
    kind: str            # "C" or "P"
    strike: float
    bid: float
    ask: float
    mid: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    open_interest: float
    volume: float


@dataclass
class Leg:
    contract: Contract
    qty: int             # +1 long, -1 short


@dataclass
class Strategy:
    family: str
    name: str
    ticker: str
    spot: float
    expiry: str
    dte: float
    legs: list[Leg] = field(default_factory=list)
    # computed stats
    net_debit: float = 0.0       # positive = pay, negative = receive credit
    capital: float = 0.0         # capital at risk / margin proxy
    max_profit: float = 0.0
    max_loss: float = 0.0
    breakevens: list[float] = field(default_factory=list)
    pop: float = 0.0             # probability of profit
    expected_value: float = 0.0  # per contract (x100 shares)
    ev_pct: float = 0.0          # EV / capital
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    score: float = 0.0

    def legs_summary(self) -> str:
        parts = []
        for leg in self.legs:
            sign = "+" if leg.qty > 0 else "-"
            parts.append(f"{sign}{abs(leg.qty)} {leg.contract.kind}{leg.contract.strike:g}")
        return " ".join(parts)


def parse_occ(symbol: str) -> tuple[str, str, str, float] | None:
    m = OCC_RE.match(symbol)
    if not m:
        return None
    root, ymd, kind, strike_raw = m.groups()
    expiry = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
    return root, expiry, kind, int(strike_raw) / 1000.0


def fetch_chain(ticker: str, timeout: float = 25.0) -> dict:
    """Fetch the raw CBOE delayed-quotes chain for one underlying."""
    resp = httpx.get(CBOE_URL.format(symbol=ticker), timeout=timeout)
    resp.raise_for_status()
    return resp.json()["data"]


def build_universe(data: dict) -> tuple[float, float, dict[str, dict[str, list[Contract]]]]:
    """Parse and filter a raw chain into {expiry: {"C": [...], "P": [...]}}."""
    spot = float(data.get("current_price") or data.get("close") or 0)
    iv30 = float(data.get("iv30") or 0)
    now = datetime.now(timezone.utc)
    chains: dict[str, dict[str, list[Contract]]] = {}

    for o in data.get("options", []):
        parsed = parse_occ(o.get("option", ""))
        if not parsed:
            continue
        _, expiry, kind, strike = parsed

        if spot <= 0 or abs(strike - spot) / spot > STRIKE_BAND:
            continue

        exp_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dte = (exp_dt - now).total_seconds() / 86400
        if dte < MIN_DTE or dte > MAX_DTE:
            continue

        bid = float(o.get("bid") or 0)
        ask = float(o.get("ask") or 0)
        if bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2
        if mid <= 0.02 or (ask - bid) / mid > MAX_SPREAD_PCT:
            continue

        iv = float(o.get("iv") or 0)
        if iv <= 0.01 or iv > 4.0:
            continue

        oi = float(o.get("open_interest") or 0)
        vol = float(o.get("volume") or 0)
        if oi < 10 and vol < 1:  # only contracts with a real market
            continue

        c = Contract(
            symbol=o["option"], expiry=expiry, dte=dte, kind=kind, strike=strike,
            bid=bid, ask=ask, mid=mid, iv=iv,
            delta=float(o.get("delta") or 0), gamma=float(o.get("gamma") or 0),
            theta=float(o.get("theta") or 0), vega=float(o.get("vega") or 0),
            open_interest=float(o.get("open_interest") or 0),
            volume=float(o.get("volume") or 0),
        )
        chains.setdefault(expiry, {"C": [], "P": []})[kind].append(c)

    for expiry in chains:
        chains[expiry]["C"].sort(key=lambda c: c.strike)
        chains[expiry]["P"].sort(key=lambda c: c.strike)

    return spot, iv30, chains


# ---------------------------------------------------------------- payoff math

def _terminal_grid(spot: float, sigma: float, t_years: float) -> tuple[np.ndarray, np.ndarray]:
    """Lognormal terminal-price grid and its probability weights."""
    sd = max(sigma * math.sqrt(max(t_years, 1e-6)), 1e-4)
    lo = spot * math.exp(-4 * sd)
    hi = spot * math.exp(4 * sd)
    prices = np.linspace(lo, hi, GRID_POINTS)
    # risk-neutral-ish drift 0: median = spot
    mu = math.log(spot) - 0.5 * sd * sd
    x = np.log(prices)
    pdf = np.exp(-((x - mu) ** 2) / (2 * sd * sd)) / (prices * sd * math.sqrt(2 * math.pi))
    weights = pdf * np.gradient(prices)
    weights /= weights.sum()
    return prices, weights


def _leg_payoff(prices: np.ndarray, leg: Leg) -> np.ndarray:
    c = leg.contract
    if c.kind == "C":
        intrinsic = np.maximum(prices - c.strike, 0.0)
    else:
        intrinsic = np.maximum(c.strike - prices, 0.0)
    return leg.qty * (intrinsic - c.mid)


def evaluate(strategy: Strategy, prices: np.ndarray, weights: np.ndarray,
             stock_qty: int = 0) -> Strategy:
    """Compute all stats for a strategy on a shared terminal grid."""
    payoff = np.zeros_like(prices)
    net_debit = 0.0
    for leg in strategy.legs:
        payoff += _leg_payoff(prices, leg)
        net_debit += leg.qty * leg.contract.mid
        strategy.net_delta += leg.qty * leg.contract.delta
        strategy.net_gamma += leg.qty * leg.contract.gamma
        strategy.net_theta += leg.qty * leg.contract.theta
        strategy.net_vega += leg.qty * leg.contract.vega

    if stock_qty:  # covered call: long stock component
        payoff += stock_qty * (prices - strategy.spot)
        strategy.net_delta += stock_qty

    strategy.net_debit = round(net_debit, 4)
    strategy.max_profit = float(payoff.max()) * 100
    strategy.max_loss = float(payoff.min()) * 100

    # capital at risk: what a broker would actually tie up
    if strategy.family == "csp":
        strike = strategy.legs[0].contract.strike
        strategy.capital = strike * 100 + net_debit * 100  # cash securing the put, net of credit
    elif strategy.family == "covered_call":
        strategy.capital = strategy.spot * 100 + net_debit * 100  # stock cost, net of credit
    elif strategy.max_loss < 0:
        strategy.capital = abs(strategy.max_loss)
    else:
        strategy.capital = max(abs(net_debit) * 100, 1.0)

    strategy.pop = float(weights[payoff > 0].sum())
    strategy.expected_value = float((payoff * weights).sum()) * 100
    strategy.ev_pct = strategy.expected_value / strategy.capital if strategy.capital > 0 else 0.0

    # breakevens: sign changes of payoff across the grid
    sign = np.sign(payoff)
    flips = np.where(np.diff(sign) != 0)[0]
    bes = []
    for i in flips[:4]:
        x0, x1 = prices[i], prices[i + 1]
        y0, y1 = payoff[i], payoff[i + 1]
        if y1 != y0:
            bes.append(round(float(x0 - y0 * (x1 - x0) / (y1 - y0)), 2))
    strategy.breakevens = bes

    # composite score: EV per unit of capital, weighted by POP
    strategy.score = strategy.ev_pct * math.sqrt(max(strategy.pop, 1e-6))
    return strategy


# ------------------------------------------------------------ strategy builder

def _pick(contracts: list[Contract], step: int = 1) -> list[Contract]:
    return contracts[::step]


def generate_strategies(ticker: str, spot: float, chains: dict) -> list[Strategy]:
    """Enumerate candidate strategies for one underlying."""
    out: list[Strategy] = []

    for expiry, sides in chains.items():
        calls, puts = sides["C"], sides["P"]
        if not calls and not puts:
            continue
        dte = (calls or puts)[0].dte
        t_years = dte / 365.0

        # shared grid per (ticker, expiry): use ATM iv as the distribution's sigma
        atm_ivs = [c.iv for c in calls + puts if abs(c.strike - spot) / spot < 0.05]
        sigma = float(np.median(atm_ivs)) if atm_ivs else 0.3
        prices, weights = _terminal_grid(spot, sigma, t_years)

        def make(family, name, legs, stock_qty=0):
            s = Strategy(family=family, name=name, ticker=ticker, spot=spot,
                         expiry=expiry, dte=round(dte, 1), legs=legs)
            s = evaluate(s, prices, weights, stock_qty=stock_qty)
            # Discard data artifacts: a strategy with (near-)zero downside is a
            # stale/crossed-quote arbitrage mirage, not a real trade. Same for
            # degenerate probabilities at the grid edges.
            if s.max_loss > -1.0 or s.capital < 5.0:
                return
            if s.pop < 0.005 or s.pop > 0.995:
                return
            out.append(s)

        # --- singles
        for c in _pick(calls):
            make("long_call", f"Long Call {c.strike:g}", [Leg(c, +1)])
        for p in _pick(puts):
            make("long_put", f"Long Put {p.strike:g}", [Leg(p, +1)])

        # --- covered call (OTM calls) / cash-secured put (OTM puts)
        for c in calls:
            if c.strike >= spot:
                make("covered_call", f"Covered Call {c.strike:g}", [Leg(c, -1)], stock_qty=1)
        for p in puts:
            if p.strike <= spot:
                make("csp", f"Cash-Secured Put {p.strike:g}", [Leg(p, -1)])

        # --- vertical spreads (widths of 1..4 strike steps)
        for width in (1, 2, 3, 4):
            for i in range(len(calls) - width):
                lo, hi = calls[i], calls[i + width]
                make("debit_spread", f"Bull Call {lo.strike:g}/{hi.strike:g}",
                     [Leg(lo, +1), Leg(hi, -1)])
                make("credit_spread", f"Bear Call {lo.strike:g}/{hi.strike:g}",
                     [Leg(lo, -1), Leg(hi, +1)])
            for i in range(len(puts) - width):
                lo, hi = puts[i], puts[i + width]
                make("debit_spread", f"Bear Put {hi.strike:g}/{lo.strike:g}",
                     [Leg(hi, +1), Leg(lo, -1)])
                make("credit_spread", f"Bull Put {hi.strike:g}/{lo.strike:g}",
                     [Leg(hi, -1), Leg(lo, +1)])

        # --- straddles / strangles (around ATM)
        atm_calls = [c for c in calls if abs(c.strike - spot) / spot < 0.10]
        put_by_strike = {p.strike: p for p in puts}
        for c in atm_calls:
            p = put_by_strike.get(c.strike)
            if p:
                make("straddle_strangle", f"Straddle {c.strike:g}",
                     [Leg(c, +1), Leg(p, +1)])
        otm_calls = [c for c in calls if spot < c.strike <= spot * 1.12]
        otm_puts = [p for p in puts if spot * 0.88 <= p.strike < spot]
        for c in otm_calls[:6]:
            for p in otm_puts[-6:]:
                make("straddle_strangle", f"Strangle {p.strike:g}P/{c.strike:g}C",
                     [Leg(c, +1), Leg(p, +1)])

        # --- iron condors (short strangle + wings)
        short_calls = [c for c in calls if spot * 1.02 <= c.strike <= spot * 1.15]
        short_puts = [p for p in puts if spot * 0.85 <= p.strike <= spot * 0.98]
        call_by_strike = {c.strike: c for c in calls}
        for sc in short_calls[:5]:
            for sp in short_puts[-5:]:
                # wings: next strikes out
                wing_c = min((c for c in calls if c.strike > sc.strike),
                             key=lambda c: c.strike, default=None)
                wing_p = max((p for p in puts if p.strike < sp.strike),
                             key=lambda p: p.strike, default=None)
                if wing_c and wing_p and call_by_strike:
                    make("iron_condor",
                         f"Iron Condor {wing_p.strike:g}/{sp.strike:g}/{sc.strike:g}/{wing_c.strike:g}",
                         [Leg(sp, -1), Leg(wing_p, +1), Leg(sc, -1), Leg(wing_c, +1)])

    return out


# ---------------------------------------------------------------- full scan

def scan(tickers: list[str] | None = None, on_progress=None) -> dict:
    """Scan all tickers and return the aggregate result payload."""
    tickers = tickers or DEFAULT_TICKERS
    started = time.time()
    all_strategies: list[Strategy] = []
    ticker_meta: list[dict] = []
    contracts_total = 0
    errors: list[str] = []

    for i, ticker in enumerate(tickers):
        if on_progress:
            on_progress(f"Fetching {ticker} chain [{i + 1}/{len(tickers)}]...")
        try:
            data = fetch_chain(ticker)
            spot, iv30, chains = build_universe(data)
            n_contracts = sum(len(s["C"]) + len(s["P"]) for s in chains.values())
            contracts_total += n_contracts
            if on_progress:
                on_progress(f"Generating strategies for {ticker} ({n_contracts} contracts)...")
            strategies = generate_strategies(ticker, spot, chains)
            all_strategies.extend(strategies)
            ticker_meta.append({
                "ticker": ticker, "spot": spot, "iv30": iv30,
                "contracts": n_contracts, "expirations": len(chains),
                "strategies": len(strategies),
            })
        except Exception as e:
            errors.append(f"{ticker}: {type(e).__name__}: {e}")

    return _aggregate(all_strategies, ticker_meta, contracts_total,
                      time.time() - started, errors)


def _strategy_row(s: Strategy) -> dict:
    return {
        "family": s.family, "name": s.name, "ticker": s.ticker,
        "legs": s.legs_summary(), "expiry": s.expiry, "dte": s.dte,
        "spot": round(s.spot, 2),
        "net_debit": round(s.net_debit * 100, 2),
        "capital": round(s.capital, 2),
        "max_profit": round(s.max_profit, 2),
        "max_loss": round(s.max_loss, 2),
        "breakevens": s.breakevens,
        "pop": round(s.pop, 4),
        "ev": round(s.expected_value, 2),
        "ev_pct": round(s.ev_pct, 4),
        "delta": round(s.net_delta, 3), "gamma": round(s.net_gamma, 4),
        "theta": round(s.net_theta, 3), "vega": round(s.net_vega, 3),
        "score": round(s.score, 4),
        "payoff_legs": [
            {"kind": l.contract.kind, "strike": l.contract.strike,
             "mid": l.contract.mid, "qty": l.qty}
            for l in s.legs
        ],
    }


def _aggregate(strategies: list[Strategy], ticker_meta: list[dict],
               contracts_total: int, elapsed: float, errors: list[str]) -> dict:
    n = len(strategies)
    if n == 0:
        return {"total_strategies": 0, "errors": errors}

    evs = np.array([s.expected_value for s in strategies])
    pops = np.array([s.pop for s in strategies])
    ev_pcts = np.array([s.ev_pct for s in strategies])

    # EV histogram (clipped to percentile band so outliers don't flatten it)
    lo, hi = np.percentile(evs, [2, 98])
    hist_counts, hist_edges = np.histogram(evs.clip(lo, hi), bins=40)

    # POP histogram
    pop_counts, pop_edges = np.histogram(pops, bins=25, range=(0, 1))

    # heatmap: ticker x family -> median ev_pct and count
    tickers = [m["ticker"] for m in ticker_meta]
    heat = []
    for t in tickers:
        row = []
        for fam in STRATEGY_FAMILIES:
            sel = [s.ev_pct for s in strategies if s.ticker == t and s.family == fam]
            row.append({
                "median_ev_pct": round(float(np.median(sel)), 4) if sel else None,
                "count": len(sel),
            })
        heat.append(row)

    # family-level stats
    family_stats = []
    for fam in STRATEGY_FAMILIES:
        sel = [s for s in strategies if s.family == fam]
        if not sel:
            continue
        f_evs = np.array([s.expected_value for s in sel])
        f_pops = np.array([s.pop for s in sel])
        family_stats.append({
            "family": fam, "count": len(sel),
            "median_ev": round(float(np.median(f_evs)), 2),
            "mean_pop": round(float(f_pops.mean()), 4),
            "pct_positive_ev": round(float((f_evs > 0).mean()), 4),
            "best_ev": round(float(f_evs.max()), 2),
        })

    # scatter sample: stratified by family so every family is visible
    scatter = []
    per_family = max(2500 // max(len(STRATEGY_FAMILIES), 1), 100)
    for fam in STRATEGY_FAMILIES:
        sel = [s for s in strategies if s.family == fam]
        step = max(len(sel) // per_family, 1)
        for s in sel[::step]:
            scatter.append({
                "family": s.family, "ticker": s.ticker, "name": s.name,
                "pop": round(s.pop, 4), "ev_pct": round(s.ev_pct, 4),
                "ev": round(s.expected_value, 2), "dte": s.dte,
            })

    # top strategies by composite score (and worst, for honesty).
    # Top 400 overall, plus the best 20 per (family, ticker) so client-side
    # filters always have depth regardless of which families dominate.
    ranked = sorted(strategies, key=lambda s: s.score, reverse=True)
    picked = ranked[:400]
    seen = set(id(s) for s in picked)
    by_bucket: dict[tuple, int] = {}
    for s in ranked:
        bucket = (s.family, s.ticker)
        if by_bucket.get(bucket, 0) >= 20:
            continue
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        if id(s) not in seen:
            seen.add(id(s))
            picked.append(s)
    top = [_strategy_row(s) for s in picked]
    worst = [_strategy_row(s) for s in ranked[-20:]]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "elapsed_seconds": round(elapsed, 1),
        "total_strategies": n,
        "total_contracts": contracts_total,
        "tickers": ticker_meta,
        "summary": {
            "pct_positive_ev": round(float((evs > 0).mean()), 4),
            "median_ev": round(float(np.median(evs)), 2),
            "mean_pop": round(float(pops.mean()), 4),
            "median_ev_pct": round(float(np.median(ev_pcts)), 4),
            "best": _strategy_row(ranked[0]),
        },
        "ev_histogram": {
            "counts": hist_counts.tolist(),
            "edges": [round(float(e), 2) for e in hist_edges],
        },
        "pop_histogram": {
            "counts": pop_counts.tolist(),
            "edges": [round(float(e), 3) for e in pop_edges],
        },
        "heatmap": {"tickers": tickers, "families": STRATEGY_FAMILIES, "cells": heat},
        "family_stats": family_stats,
        "scatter": scatter,
        "top_strategies": top,
        "worst_strategies": worst,
        "errors": errors,
    }


if __name__ == "__main__":
    import json as _json
    result = scan(["AAPL", "NVDA"], on_progress=print)
    print(f"\n{result['total_strategies']} strategies from {result['total_contracts']} contracts "
          f"in {result['elapsed_seconds']}s")
    print("best:", _json.dumps(result["summary"]["best"], indent=2)[:400])
