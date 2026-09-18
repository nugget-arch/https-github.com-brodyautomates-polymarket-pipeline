#!/usr/bin/env python3
"""
Order Flow / Footprint prototype — BTC, real data from Binance.

Zero third-party dependencies: uses only the Python standard library so it
runs anywhere with Python 3.8+. Market data comes from Binance's public
market-data endpoint (data-api.binance.vision), which serves:

  * klines            -> OHLCV candles + real taker-buy volume (aggressor)
  * aggTrades         -> individual trades with the aggressor side (`m`)

From these we derive genuine order-flow signals:

  * per-candle delta      = taker-buy volume - taker-sell volume   (from klines)
  * volume profile        = volume distributed by price into bins
  * vPOC / VAH / VAL      = point of control + 70% value area
  * per-candle footprint  = real buy/sell volume by price level (from aggTrades)

Run:   python3 orderflow/server.py   then open  http://localhost:8787
"""
from __future__ import annotations

import json
import math
import os
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "https://data-api.binance.vision"
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("ORDERFLOW_PORT", "8787"))

# Milliseconds per supported interval.
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
}


# --------------------------------------------------------------------------- #
# Binance client (stdlib only, proxy/CA aware)
# --------------------------------------------------------------------------- #
def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and os.path.exists(bundle):
        try:
            ctx.load_verify_locations(bundle)
        except ssl.SSLError:
            pass
    return ctx


_CTX = _ssl_context()


def _get(path: str, params: dict) -> object:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "orderflow-proto/1.0"})
    with urllib.request.urlopen(req, context=_CTX, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_klines(symbol: str, interval: str, limit: int) -> list:
    return _get("/api/v3/klines", {
        "symbol": symbol, "interval": interval, "limit": limit,
    })


def fetch_agg_trades(symbol: str, start_ms: int, end_ms: int, max_pages: int = 25) -> list:
    """Page through aggTrades in a [start, end) window using fromId."""
    trades: list = []
    from_id: int | None = None
    for _ in range(max_pages):
        params: dict = {"symbol": symbol, "limit": 1000}
        if from_id is None:
            params["startTime"] = start_ms
            params["endTime"] = end_ms
        else:
            params["fromId"] = from_id
        batch = _get("/api/v3/aggTrades", params)
        if not batch:
            break
        for t in batch:
            if t["T"] >= end_ms:
                return trades
            trades.append(t)
        if len(batch) < 1000:
            break
        from_id = batch[-1]["a"] + 1
    return trades


# --------------------------------------------------------------------------- #
# Order-flow math
# --------------------------------------------------------------------------- #
def parse_candles(raw: list) -> list:
    """Binance kline layout: [openTime,o,h,l,c,vol,closeTime,qVol,nTrades,
    takerBuyBase,takerBuyQuote,ignore]."""
    out = []
    for k in raw:
        vol = float(k[5])
        taker_buy = float(k[9])
        out.append({
            "t": int(k[0]),
            "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]),
            "v": vol,
            "delta": round(2 * taker_buy - vol, 4),  # buy - sell aggressor volume
        })
    return out


def volume_profile(candles: list, bins: int = 90) -> dict:
    """Distribute each candle's volume across price bins between its low/high,
    splitting into buy/sell using the candle's taker delta ratio."""
    lo = min(c["l"] for c in candles)
    hi = max(c["h"] for c in candles)
    if hi <= lo:
        hi = lo + 1.0
    step = (hi - lo) / bins
    buckets = [{"buy": 0.0, "sell": 0.0} for _ in range(bins)]

    for c in candles:
        buy_v = (c["v"] + c["delta"]) / 2.0   # taker-buy volume
        sell_v = c["v"] - buy_v
        b0 = max(0, int((c["l"] - lo) / step))
        b1 = min(bins - 1, int((c["h"] - lo) / step))
        span = b1 - b0 + 1
        for b in range(b0, b1 + 1):
            buckets[b]["buy"] += buy_v / span
            buckets[b]["sell"] += sell_v / span

    profile = []
    for i, bucket in enumerate(buckets):
        profile.append({
            "price": round(lo + (i + 0.5) * step, 2),
            "buy": round(bucket["buy"], 4),
            "sell": round(bucket["sell"], 4),
            "vol": round(bucket["buy"] + bucket["sell"], 4),
        })

    vpoc, vah, val = value_area(profile)
    return {"profile": profile, "vpoc": vpoc, "vah": vah, "val": val,
            "priceLow": round(lo, 2), "priceHigh": round(hi, 2)}


def value_area(profile: list, share: float = 0.70) -> tuple:
    """Point of control + 70% value-area high/low, grown outward from POC."""
    if not profile:
        return (0.0, 0.0, 0.0)
    total = sum(p["vol"] for p in profile)
    poc = max(range(len(profile)), key=lambda i: profile[i]["vol"])
    lo = hi = poc
    acc = profile[poc]["vol"]
    target = total * share
    while acc < target and (lo > 0 or hi < len(profile) - 1):
        up = profile[hi + 1]["vol"] if hi < len(profile) - 1 else -1
        dn = profile[lo - 1]["vol"] if lo > 0 else -1
        if up >= dn:
            hi += 1
            acc += profile[hi]["vol"]
        else:
            lo -= 1
            acc += profile[lo]["vol"]
    return (profile[poc]["price"], profile[hi]["price"], profile[lo]["price"])


def footprint(symbol: str, open_ms: int, interval: str, bins: int = 40) -> dict:
    """Real tick-level footprint for a single candle, from aggTrades."""
    dur = INTERVAL_MS.get(interval, 60_000)
    trades = fetch_agg_trades(symbol, open_ms, open_ms + dur)
    if not trades:
        return {"rows": [], "buy": 0.0, "sell": 0.0, "delta": 0.0, "trades": 0}

    prices = [float(t["p"]) for t in trades]
    lo, hi = min(prices), max(prices)
    if hi <= lo:
        hi = lo + 1.0
    step = (hi - lo) / bins
    rows = [{"buy": 0.0, "sell": 0.0} for _ in range(bins)]
    tot_buy = tot_sell = 0.0

    for t in trades:
        p = float(t["p"])
        q = float(t["q"])
        b = min(bins - 1, int((p - lo) / step))
        # m == True  -> buyer is maker  -> aggressor is the SELLER
        # m == False -> buyer is taker  -> aggressor is the BUYER
        if t["m"]:
            rows[b]["sell"] += q
            tot_sell += q
        else:
            rows[b]["buy"] += q
            tot_buy += q

    out = []
    for i in range(bins - 1, -1, -1):  # high price first
        r = rows[i]
        if r["buy"] == 0 and r["sell"] == 0:
            continue
        out.append({
            "price": round(lo + (i + 0.5) * step, 2),
            "buy": round(r["buy"], 4),
            "sell": round(r["sell"], 4),
            "delta": round(r["buy"] - r["sell"], 4),
        })
    return {
        "rows": out,
        "buy": round(tot_buy, 4),
        "sell": round(tot_sell, 4),
        "delta": round(tot_buy - tot_sell, 4),
        "trades": len(trades),
    }


def build_chart(symbol: str, interval: str, candles_n: int) -> dict:
    raw = fetch_klines(symbol, interval, candles_n)
    candles = parse_candles(raw)
    prof = volume_profile(candles)
    cum_delta = round(sum(c["delta"] for c in candles), 4)
    total_vol = round(sum(c["v"] for c in candles), 4)
    return {
        "symbol": symbol,
        "interval": interval,
        "candles": candles,
        "lastPrice": candles[-1]["c"] if candles else 0.0,
        "cumDelta": cum_delta,
        "totalVol": total_vol,
        **prof,
    }


# --------------------------------------------------------------------------- #
# Footprint seed — real bid/ask clusters per candle (for immediate display)
# --------------------------------------------------------------------------- #
def suggest_basetick(price: float) -> float:
    """A fine, price-scaled base tick so live clusters stay bounded but precise.
    BTC(~77k)->1, ETH(~3k)->0.1, SOL(~150)->0.01, BNB(~600)->0.1."""
    if price <= 0:
        return 0.01
    exp = math.floor(math.log10(price)) - 4
    return float(10 ** exp)


def footprint_levels(symbol: str, open_ms: int, interval: str, basetick: float) -> dict:
    """Real per-price-level bid/ask volume for one candle, keyed by tick index.
    Returns compact rows [[idx, bid, ask], ...] where price = idx * basetick."""
    dur = INTERVAL_MS.get(interval, 60_000)
    trades = fetch_agg_trades(symbol, open_ms, open_ms + dur)
    levels: dict = {}
    buy = sell = 0.0
    for t in trades:
        p = float(t["p"])
        q = float(t["q"])
        idx = int(round(p / basetick))
        cell = levels.setdefault(idx, [0.0, 0.0])  # [bid(=sell aggr), ask(=buy aggr)]
        if t["m"]:                 # buyer is maker -> aggressive SELL hits the bid
            cell[0] += q
            sell += q
        else:                      # buyer is taker -> aggressive BUY lifts the ask
            cell[1] += q
            buy += q
    rows = [[idx, round(v[0], 4), round(v[1], 4)] for idx, v in sorted(levels.items())]
    poc_idx = max(levels, key=lambda i: levels[i][0] + levels[i][1]) if levels else 0
    return {
        "rows": rows,
        "buy": round(buy, 4),
        "sell": round(sell, 4),
        "delta": round(buy - sell, 4),
        "poc": round(poc_idx * basetick, 2),
        "trades": len(trades),
    }


def build_seed(symbol: str, interval: str, candles_n: int, fp_n: int) -> dict:
    """Everything the client needs to render immediately, before the live WS
    takes over: full-window candles + profile + value area, plus real footprint
    clusters for the most recent `fp_n` candles."""
    raw = fetch_klines(symbol, interval, candles_n)
    candles = parse_candles(raw)
    prof = volume_profile(candles)
    basetick = suggest_basetick(candles[-1]["c"] if candles else 1.0)

    footprints = []
    for c in candles[-fp_n:]:
        fp = footprint_levels(symbol, c["t"], interval, basetick)
        footprints.append({
            "t": c["t"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"],
            **fp,
        })

    return {
        "symbol": symbol,
        "interval": interval,
        "intervalMs": INTERVAL_MS.get(interval, 60_000),
        "basetick": basetick,
        "candles": candles,
        "footprints": footprints,
        "lastPrice": candles[-1]["c"] if candles else 0.0,
        "cumDelta": round(sum(c["delta"] for c in candles), 4),
        "totalVol": round(sum(c["v"] for c in candles), 4),
        "serverTime": _get("/api/v3/time", {}).get("serverTime", 0),
        **prof,
    }


# Short-lived seed cache so rapid reloads / multiple viewers don't refetch the
# whole footprint window. Live updates ride the WebSocket, so a few seconds of
# staleness on the historical seed is invisible.
_SEED_CACHE: dict = {}
_SEED_LOCK = threading.Lock()
_SEED_TTL = 60.0


def _seed_cached(symbol: str, interval: str, candles_n: int, fp_n: int) -> dict:
    key = (symbol, interval, candles_n, fp_n)
    now = time.time()
    with _SEED_LOCK:
        hit = _SEED_CACHE.get(key)
        if hit and now - hit[0] < _SEED_TTL:
            return hit[1]
    data = build_seed(symbol, interval, candles_n, fp_n)
    with _SEED_LOCK:
        _SEED_CACHE[key] = (now, data)
    return data


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/footprint.js": ("footprint.js", "application/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("· " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        def arg(name, default):
            return qs.get(name, [default])[0]

        try:
            if path == "/api/chart":
                data = build_chart(
                    arg("symbol", "BTCUSDT").upper(),
                    arg("interval", "1m"),
                    min(500, max(20, int(arg("candles", "90")))),
                )
                return self._json(data)

            if path == "/api/footprint":
                data = footprint(
                    arg("symbol", "BTCUSDT").upper(),
                    int(arg("openTime", "0")),
                    arg("interval", "1m"),
                )
                return self._json(data)

            if path == "/api/seed":
                sym = arg("symbol", "BTCUSDT").upper()
                itv = arg("interval", "1m")
                cn = min(300, max(20, int(arg("candles", "90"))))
                fp = min(40, max(4, int(arg("fp", "18"))))
                data = _seed_cached(sym, itv, cn, fp)
                return self._json(data)

            if path in STATIC:
                fname, ctype = STATIC[path]
                with open(os.path.join(HERE, fname), "rb") as fh:
                    return self._send(200, fh.read(), ctype)

            self._send(404, b"not found", "text/plain")
        except urllib.error.HTTPError as exc:
            self._json({"error": f"binance {exc.code}", "detail": exc.reason}, 502)
        except Exception as exc:  # noqa: BLE001 - prototype: surface any error
            self._json({"error": str(exc)}, 500)


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Order-flow prototype running -> http://localhost:{PORT}")
    print("Data: Binance public market data (data-api.binance.vision)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()


if __name__ == "__main__":
    main()
