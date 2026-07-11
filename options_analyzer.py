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

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "AMD", "SPY", "QQQ",
    "NFLX", "AVGO", "JPM", "BAC", "XOM", "COIN", "PLTR", "INTC", "MU", "ORCL",
    "DIS", "BA", "IWM", "CRM",
]

# Universe constraints
MIN_DTE = 7           # days to expiration
MAX_DTE = 120
STRIKE_BAND = 0.25    # only strikes within ±25% of spot
MAX_SPREAD_PCT = 0.60 # discard contracts whose bid/ask spread is >60% of mid
GRID_POINTS = 320     # integration grid resolution

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
    # execution-adjusted (enter long legs at ask, short legs at bid)
    slippage: float = 0.0        # total half-spread cost vs mid, dollars
    pop_exec: float = 0.0
    ev_exec: float = 0.0
    cvar5: float = 0.0           # expected P/L in the worst 5% of scenarios
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

def _implied_forward(spot: float, calls: list[Contract], puts: list[Contract]) -> float:
    """
    Market-implied forward from put-call parity: F = K + (C - P) at each
    near-ATM strike. Uses the market's own pricing of carry (rates minus
    dividends) instead of assuming F = spot.
    """
    put_by_k = {p.strike: p for p in puts}
    estimates = []
    for c in calls:
        p = put_by_k.get(c.strike)
        if p and abs(c.strike - spot) / spot < 0.08:
            estimates.append(c.strike + (c.mid - p.mid))
    if not estimates:
        return spot
    f = float(np.median(estimates))
    # sanity clamp: a forward >5% away from spot inside 120 DTE is bad data
    return f if 0.95 * spot <= f <= 1.05 * spot else spot


def _terminal_grid(forward: float, sigma: float, t_years: float) -> tuple[np.ndarray, np.ndarray]:
    """Lognormal terminal-price grid and its probability weights.

    Centered so that E[S_T] equals the market-implied forward (risk-neutral
    pricing measure): mu = ln(F) - sigma^2*T/2.
    """
    sd = max(sigma * math.sqrt(max(t_years, 1e-6)), 1e-4)
    lo = forward * math.exp(-4 * sd)
    hi = forward * math.exp(4 * sd)
    prices = np.linspace(lo, hi, GRID_POINTS)
    mu = math.log(forward) - 0.5 * sd * sd
    x = np.log(prices)
    pdf = np.exp(-((x - mu) ** 2) / (2 * sd * sd)) / (prices * sd * math.sqrt(2 * math.pi))
    weights = pdf * np.gradient(prices)
    weights /= weights.sum()
    return prices, weights


_erf_vec = np.frompyfunc(math.erf, 1, 1)


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf_vec(x / math.sqrt(2)).astype(float))


def _market_density(forward: float, sigma_atm: float, t_years: float,
                    calls: list[Contract], puts: list[Contract]
                    ) -> tuple[np.ndarray, np.ndarray, bool]:
    """
    Market-implied terminal density via Breeden-Litzenberger: the density is
    the second derivative of the call-price curve C(K). We build C(K) from
    Black-76 with the OBSERVED IV smile (OTM puts below the forward, OTM
    calls above, lightly smoothed, flat-extrapolated), then differentiate
    numerically. This bakes the market's skew into every probability instead
    of assuming a single lognormal.

    Returns (prices, weights, used_smile). Falls back to the lognormal grid
    when the smile is too sparse or the resulting density is degenerate.
    """
    smile = [(p.strike, p.iv) for p in puts if p.strike <= forward]
    smile += [(c.strike, c.iv) for c in calls if c.strike > forward]
    smile.sort()
    if len(smile) < 6:
        prices, weights = _terminal_grid(forward, sigma_atm, t_years)
        return prices, weights, False

    ks = np.array([k for k, _ in smile], dtype=float)
    ivs = np.array([v for _, v in smile], dtype=float)
    if len(ivs) >= 7:  # light 3-point smoothing, endpoints kept
        inner = np.convolve(ivs, np.ones(3) / 3, mode="valid")
        ivs = np.concatenate([[ivs[0]], inner, [ivs[-1]]])

    sd = max(sigma_atm * math.sqrt(max(t_years, 1e-6)), 1e-4)
    prices = np.linspace(forward * math.exp(-4 * sd), forward * math.exp(4 * sd), GRID_POINTS)
    iv_k = np.clip(np.interp(prices, ks, ivs), 0.01, 4.0)

    # Black-76 call prices on the strike grid (discount factor irrelevant for
    # the normalized density)
    st = iv_k * math.sqrt(max(t_years, 1e-6))
    d1 = (np.log(forward / prices) + 0.5 * st * st) / st
    d2 = d1 - st
    call_prices = forward * _norm_cdf(d1) - prices * _norm_cdf(d2)

    dk = prices[1] - prices[0]
    density = np.gradient(np.gradient(call_prices, dk), dk)
    density = np.clip(density, 0.0, None)
    total = density.sum() * dk
    if total <= 0:
        p2, w2 = _terminal_grid(forward, sigma_atm, t_years)
        return p2, w2, False
    weights = density * dk / total

    # sanity: the density must reprice the forward within 2%
    if abs(float((prices * weights).sum()) - forward) / forward > 0.02:
        p2, w2 = _terminal_grid(forward, sigma_atm, t_years)
        return p2, w2, False
    return prices, weights, True


def _leg_payoff(prices: np.ndarray, leg: Leg) -> np.ndarray:
    c = leg.contract
    if c.kind == "C":
        intrinsic = np.maximum(prices - c.strike, 0.0)
    else:
        intrinsic = np.maximum(c.strike - prices, 0.0)
    return leg.qty * (intrinsic - c.mid)


def _payoff_scalar(strategy: Strategy, S: float, stock_qty: int) -> float:
    """Exact per-share payoff of the strategy at terminal price S."""
    v = 0.0
    for leg in strategy.legs:
        c = leg.contract
        intrinsic = max(S - c.strike, 0.0) if c.kind == "C" else max(c.strike - S, 0.0)
        v += leg.qty * (intrinsic - c.mid)
    if stock_qty:
        v += stock_qty * (S - strategy.spot)
    return v


def _analytic_extremes(strategy: Strategy, stock_qty: int) -> tuple[float, float]:
    """
    True max profit / max loss over S in [0, inf).

    The payoff is piecewise linear with kinks only at the strikes, so its
    extremes occur at S=0, at a strike, or asymptotically as S -> inf
    (slope = net long calls + stock). Returns per-contract dollars (x100);
    +inf for unlimited upside.
    """
    kinks = [0.0] + sorted({leg.contract.strike for leg in strategy.legs})
    vals = [_payoff_scalar(strategy, S, stock_qty) for S in kinks]
    slope_inf = sum(leg.qty for leg in strategy.legs if leg.contract.kind == "C") + stock_qty

    max_p = max(vals) * 100
    max_l = min(vals) * 100
    if slope_inf > 0:
        max_p = math.inf
    elif slope_inf < 0:
        max_l = -math.inf  # unreachable with current families, kept for safety
    return max_p, max_l


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
    strategy.max_profit, strategy.max_loss = _analytic_extremes(strategy, stock_qty)

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

    # Execution-adjusted stats: mid is not a fillable price. Entering long
    # legs at ask and short legs at bid costs one half-spread per leg, which
    # shifts the whole P/L curve down by a constant.
    half_spreads = sum(abs(leg.qty) * (leg.contract.ask - leg.contract.bid) / 2
                       for leg in strategy.legs)
    strategy.slippage = half_spreads * 100
    strategy.ev_exec = strategy.expected_value - strategy.slippage
    strategy.pop_exec = float(weights[payoff > half_spreads].sum())

    # CVaR 5%: probability-weighted mean P/L over the worst 5% of scenarios
    order = np.argsort(payoff)
    cum = np.cumsum(weights[order])
    tail = cum <= 0.05
    if not tail.any():
        tail[0] = True
    tw = weights[order][tail]
    strategy.cvar5 = float((payoff[order][tail] * tw).sum() / tw.sum()) * 100

    # breakevens: exact roots of the piecewise-linear payoff. Kinks only at
    # strikes, so solve each linear segment (plus the tail to infinity).
    kinks = [0.0] + sorted({leg.contract.strike for leg in strategy.legs})
    kink_vals = [_payoff_scalar(strategy, S, stock_qty) for S in kinks]
    bes = []
    for i in range(len(kinks) - 1):
        y0, y1 = kink_vals[i], kink_vals[i + 1]
        if y0 == 0 or (y0 < 0) == (y1 < 0):
            continue
        x0, x1 = kinks[i], kinks[i + 1]
        bes.append(round(x0 - y0 * (x1 - x0) / (y1 - y0), 2))
    slope_inf = sum(leg.qty for leg in strategy.legs if leg.contract.kind == "C") + stock_qty
    if slope_inf != 0 and kink_vals[-1] != 0 and (kink_vals[-1] < 0) == (slope_inf > 0):
        bes.append(round(kinks[-1] - kink_vals[-1] / slope_inf, 2))
    strategy.breakevens = bes[:4]

    # composite score: EV per unit of capital, weighted by POP
    strategy.score = strategy.ev_pct * math.sqrt(max(strategy.pop, 1e-6))
    return strategy


# ------------------------------------------------------------ strategy builder

def _pick(contracts: list[Contract], step: int = 1) -> list[Contract]:
    return contracts[::step]


def _quantiles(prices: np.ndarray, weights: np.ndarray, n: int = 101) -> list[float]:
    """Quantile function of the terminal density, for Monte Carlo sampling."""
    cw = np.cumsum(weights)
    qs = np.linspace(0.005, 0.995, n)
    return [round(float(np.interp(q, cw, prices)), 2) for q in qs]


def generate_strategies(ticker: str, spot: float, chains: dict
                        ) -> tuple[list[Strategy], dict[str, list[float]]]:
    """Enumerate candidate strategies for one underlying.

    Also returns the quantile function of each expiry's terminal density so
    the frontend can Monte Carlo-sample consistent terminal prices.
    """
    out: list[Strategy] = []
    densities: dict[str, list[float]] = {}

    for expiry, sides in chains.items():
        calls, puts = sides["C"], sides["P"]
        if not calls and not puts:
            continue
        dte = (calls or puts)[0].dte
        t_years = dte / 365.0

        # shared grid per (ticker, expiry): market-implied density built from
        # the observed IV smile (Breeden-Litzenberger), centered on the
        # put-call-parity forward; lognormal fallback for sparse smiles
        atm_ivs = [c.iv for c in calls + puts if abs(c.strike - spot) / spot < 0.05]
        sigma = float(np.median(atm_ivs)) if atm_ivs else 0.3
        forward = _implied_forward(spot, calls, puts)
        prices, weights, _used_smile = _market_density(forward, sigma, t_years, calls, puts)
        densities[expiry] = _quantiles(prices, weights)

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

    return out, densities


# ---------------------------------------------------------------- full scan

def scan(tickers: list[str] | None = None, on_progress=None) -> dict:
    """Scan all tickers and return the aggregate result payload."""
    tickers = tickers or DEFAULT_TICKERS
    started = time.time()
    all_strategies: list[Strategy] = []
    ticker_meta: list[dict] = []
    smiles: dict[str, dict] = {}
    all_densities: dict[str, dict] = {}
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
            strategies, densities = generate_strategies(ticker, spot, chains)
            all_strategies.extend(strategies)
            all_densities[ticker] = densities
            ticker_meta.append({
                "ticker": ticker, "spot": spot, "iv30": iv30,
                "contracts": n_contracts, "expirations": len(chains),
                "strategies": len(strategies),
            })
            smile = _smile_snapshot(spot, chains)
            if smile:
                smiles[ticker] = smile
        except Exception as e:
            errors.append(f"{ticker}: {type(e).__name__}: {e}")

    result = _aggregate(all_strategies, ticker_meta, contracts_total,
                        time.time() - started, errors)
    result["smiles"] = smiles
    result["densities"] = all_densities
    return result


def _smile_snapshot(spot: float, chains: dict) -> dict | None:
    """OTM IV smile of the expiry nearest 30 DTE, for the UI chart."""
    best = None
    for expiry, sides in chains.items():
        cs = sides["C"] or sides["P"]
        if not cs:
            continue
        dte = cs[0].dte
        if best is None or abs(dte - 30) < abs(best[1] - 30):
            best = (expiry, dte, sides)
    if not best:
        return None
    expiry, dte, sides = best
    pts = [[p.strike, round(p.iv * 100, 2)] for p in sides["P"] if p.strike <= spot]
    pts += [[c.strike, round(c.iv * 100, 2)] for c in sides["C"] if c.strike > spot]
    pts.sort()
    if len(pts) < 6:
        return None
    return {"expiry": expiry, "dte": round(dte, 1), "spot": round(spot, 2), "points": pts}


def _strategy_row(s: Strategy) -> dict:
    return {
        "family": s.family, "name": s.name, "ticker": s.ticker,
        "legs": s.legs_summary(), "expiry": s.expiry, "dte": s.dte,
        "spot": round(s.spot, 2),
        "net_debit": round(s.net_debit * 100, 2),
        "capital": round(s.capital, 2),
        "max_profit": None if math.isinf(s.max_profit) else round(s.max_profit, 2),
        "max_loss": None if math.isinf(s.max_loss) else round(s.max_loss, 2),
        "breakevens": s.breakevens,
        "pop": round(s.pop, 4),
        "ev": round(s.expected_value, 2),
        "ev_pct": round(s.ev_pct, 4),
        "roc_annual": round(s.ev_pct * 365.0 / max(s.dte, 1.0), 4),
        "slippage": round(s.slippage, 2),
        "pop_exec": round(s.pop_exec, 4),
        "ev_exec": round(s.ev_exec, 2),
        "cvar5": round(s.cvar5, 2),
        "roc_annual_exec": round((s.ev_exec / s.capital) * 365.0 / max(s.dte, 1.0), 4) if s.capital > 0 else 0.0,
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

    # "top picks": consistency-profile screen at EXECUTABLE prices (long legs
    # at ask, short at bid) — mid-price mirages on wide-spread contracts do
    # not qualify. High probability of profit, positive executable EV,
    # defined risk, meaningful annualized return, and a per-ticker diversity
    # cap so the list is investable as a portfolio.
    def roc_annual_exec(s: Strategy) -> float:
        return (s.ev_exec / s.capital) * 365.0 / max(s.dte, 1.0) if s.capital > 0 else 0.0

    picks_pool = [
        s for s in strategies
        if s.pop_exec >= 0.65
        and s.ev_exec > 0
        and not math.isinf(s.max_profit) and not math.isinf(-s.max_loss)
        and s.capital <= 30000
        and 0.08 <= roc_annual_exec(s) <= 3.0   # >300%/yr "sure things" are data artifacts
        and s.dte >= 10
    ]
    picks_pool.sort(key=lambda s: s.pop_exec * roc_annual_exec(s), reverse=True)
    top_picks = []
    per_ticker: dict[str, int] = {}
    for s in picks_pool:
        if per_ticker.get(s.ticker, 0) >= 6:
            continue
        per_ticker[s.ticker] = per_ticker.get(s.ticker, 0) + 1
        top_picks.append(_strategy_row(s))
        if len(top_picks) >= 80:
            break

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
        "top_picks": top_picks,
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
