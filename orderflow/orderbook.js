/* L2 order book model + real iceberg / absorption detection.

   Fed by two live sources (browser -> Binance):
     - @depth20@100ms : top-of-book resting sizes (the visible ladder)
     - @aggTrade      : executed trades (what actually got filled)

   Iceberg (real, needs L2): a hidden refilling limit order shows up as a price
   level where the EXECUTED volume greatly exceeds the size the book ever
   DISPLAYED there — the order keeps refilling faster than it's eaten.

   Absorption (real, needs L2): a large resting level that soaks up heavy
   aggression without the price breaking through it.
*/

export class OrderBook {
  constructor(cfg = {}) {
    this.bids = new Map();   // price -> size (resting)
    this.asks = new Map();
    this.lastUpdateId = 0;
    // per-price rolling stats for iceberg/absorption over a time window
    this.track = new Map();  // price -> {maxShown, executed, hits, side, refills, lastShown, t}
    this.cfg = {
      windowMs: 90_000,        // rolling memory per price level
      icebergExecMult: 2.5,    // executed >= mult * maxShown => refilling (iceberg)
      icebergMinExec: 0,       // set per-symbol (min executed to matter)
      absorbSizePct: 0.90,     // resting size in top decile of the book
      absorbExecMult: 1.2,     // executed >= mult * maxShown but level still there
      ...cfg,
    };
    this.signals = [];         // recent {type, side, price, detail, t}
  }

  seed(snapshot) {
    this.bids.clear(); this.asks.clear();
    for (const [p, q] of snapshot.bids) if (q > 0) this.bids.set(p, q);
    for (const [p, q] of snapshot.asks) if (q > 0) this.asks.set(p, q);
    this.lastUpdateId = snapshot.lastUpdateId || 0;
  }

  /** partial book depth (@depth20) message: {bids:[[p,q]...], asks:[...]} */
  applyDepth(d) {
    const bids = d.bids || d.b || [];
    const asks = d.asks || d.a || [];
    // @depth20 sends the full top-20 each time -> replace
    this.bids.clear(); this.asks.clear();
    for (const [p, q] of bids) { const P = +p, Q = +q; if (Q > 0) this.bids.set(P, Q); }
    for (const [p, q] of asks) { const P = +p, Q = +q; if (Q > 0) this.asks.set(P, Q); }
    // remember the largest size ever shown at each price (for iceberg contrast)
    const now = Date.now();
    for (const [P, Q] of this.bids) this._shown(P, Q, "bid", now);
    for (const [P, Q] of this.asks) this._shown(P, Q, "ask", now);
  }

  _shown(price, size, side, now) {
    let t = this.track.get(price);
    if (!t) { t = { maxShown: 0, executed: 0, hits: 0, side, refills: 0, lastShown: 0, t: now }; this.track.set(price, t); }
    // a "refill": size grows back after having been eaten down
    if (size > t.lastShown * 1.5 && t.lastShown > 0) t.refills++;
    t.lastShown = size;
    if (size > t.maxShown) t.maxShown = size;
    t.side = side;
    t.t = now;
  }

  /** @aggTrade: record executed volume at the traded price. */
  applyTrade(price, qty, isSell) {
    const now = Date.now();
    // snap to nearest tracked price (book is at exchange tick granularity)
    let t = this.track.get(price);
    if (!t) { t = { maxShown: 0, executed: 0, hits: 0, side: isSell ? "bid" : "ask", refills: 0, lastShown: 0, t: now }; this.track.set(price, t); }
    t.executed += qty;
    t.hits++;
    t.t = now;
    this._detect(price, t, now);
  }

  _detect(price, t, now) {
    const c = this.cfg;
    // ICEBERG: much more executed than was ever displayed here, with refills
    if (t.maxShown > 0 && t.executed >= c.icebergExecMult * t.maxShown &&
        t.executed >= c.icebergMinExec && t.refills >= 1) {
      this._emit("iceberg", t.side, price,
        `Iceberg: ${t.executed.toFixed(2)} ejec. vs ${t.maxShown.toFixed(2)} visible`, now, price);
    }
    // ABSORPTION: big resting level, heavily hit, still sitting there
    const book = t.side === "bid" ? this.bids : this.asks;
    const resting = book.get(price) || 0;
    if (resting > 0 && this._isLarge(resting, t.side) &&
        t.executed >= c.absorbExecMult * t.maxShown && t.maxShown > 0) {
      this._emit("absorption", t.side, price,
        `Absorción: ${t.executed.toFixed(2)} absorbidos, ${resting.toFixed(2)} en pie`, now, price);
    }
  }

  _isLarge(size, side) {
    const sizes = [...(side === "bid" ? this.bids : this.asks).values()].sort((a, b) => a - b);
    if (!sizes.length) return false;
    const idx = Math.floor(sizes.length * this.cfg.absorbSizePct);
    return size >= sizes[Math.min(idx, sizes.length - 1)];
  }

  _emit(type, side, price, detail, t, key) {
    const last = this.signals[0];
    if (last && last.type === type && last.priceKey === key && t - last.t < 8000) return; // debounce
    this.signals.unshift({ type, side, price, detail, t, priceKey: key });
    this.signals = this.signals.slice(0, 40);
  }

  /** flags for the ladder: Set of prices currently flagged iceberg/absorption */
  flagged(kind, sinceMs = 20000) {
    const now = Date.now();
    const s = new Set();
    for (const sig of this.signals)
      if (sig.type === kind && now - sig.t < sinceMs) s.add(sig.priceKey);
    return s;
  }

  best() {
    let bb = -Infinity, ba = Infinity;
    for (const p of this.bids.keys()) if (p > bb) bb = p;
    for (const p of this.asks.keys()) if (p < ba) ba = p;
    return { bid: bb === -Infinity ? null : bb, ask: ba === Infinity ? null : ba };
  }

  totals() {
    let b = 0, a = 0;
    for (const q of this.bids.values()) b += q;
    for (const q of this.asks.values()) a += q;
    return { bid: b, ask: a, imbalance: b + a > 0 ? (b - a) / (b + a) : 0 };
  }

  prune(now = Date.now()) {
    for (const [p, t] of this.track) if (now - t.t > this.cfg.windowMs) this.track.delete(p);
  }
}
