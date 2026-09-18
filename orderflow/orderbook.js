/* Full L2 order book with correct snapshot + diff synchronization, plus real
   iceberg / absorption detection and heatmap aggregation.

   Sync protocol (Binance managed-book spec):
     1. beginSync()            -> start buffering @depth diff events
     2. fetch REST snapshot    -> seedSnapshot(snap) with its lastUpdateId
     3. drop buffered events with u <= lastUpdateId, then apply the rest
     4. each subsequent event must chain (U == prevFinalId + 1) or we re-sync

   Sources (browser -> Binance):
     - REST /api/v3/depth?limit=1000  (snapshot)
     - @depth@100ms                    (diff stream, event e:"depthUpdate")
   Falls back to @depth20 partial book if diff sync is unavailable.
*/

export class OrderBook {
  constructor(cfg = {}) {
    this.bids = new Map();       // price -> size
    this.asks = new Map();
    this.lastUpdateId = 0;
    this.syncing = false;
    this.buffer = [];
    this.prevFinalId = 0;
    this.resyncs = 0;
    this.updates = 0;            // diff events applied (for ups metric)
    this.onResync = null;        // callback to request a fresh snapshot

    this.track = new Map();      // price -> {maxShown, executed, hits, side, refills, lastShown, t}
    this.cfg = {
      windowMs: 90_000, icebergExecMult: 2.5, icebergMinExec: 0,
      absorbSizePct: 0.90, absorbExecMult: 1.2, ...cfg,
    };
    this.signals = [];
  }

  // ------------------------------------------------------------ sync ----
  beginSync() { this.syncing = true; this.buffer = []; this.bids.clear(); this.asks.clear(); }

  seedSnapshot(snap) {
    this.bids.clear(); this.asks.clear();
    for (const [p, q] of snap.bids) { const P = +p, Q = +q; if (Q > 0) this.bids.set(P, Q); }
    for (const [p, q] of snap.asks) { const P = +p, Q = +q; if (Q > 0) this.asks.set(P, Q); }
    this.lastUpdateId = snap.lastUpdateId || 0;
    this.prevFinalId = this.lastUpdateId;
    // drain buffered diffs that are newer than the snapshot
    const buf = this.buffer; this.buffer = []; this.syncing = false;
    for (const d of buf) { if ((d.u || 0) <= this.lastUpdateId) continue; this._applyDiff(d, true); }
    this._markShownAll();
  }

  /** @depth diff event (e:"depthUpdate", U, u, b, a) OR partial @depth20 */
  applyDepth(d) {
    if (d.e === "depthUpdate") {                 // incremental diff
      if (this.syncing) { this.buffer.push(d); return; }
      this._applyDiff(d, false);
    } else {                                      // partial book (fallback)
      this.bids.clear(); this.asks.clear();
      for (const [p, q] of (d.bids || d.b || [])) { const P = +p, Q = +q; if (Q > 0) this.bids.set(P, Q); }
      for (const [p, q] of (d.asks || d.a || [])) { const P = +p, Q = +q; if (Q > 0) this.asks.set(P, Q); }
      this.updates++; this._markShownAll();
    }
  }

  _applyDiff(d, drained) {
    const U = d.U || 0, u = d.u || 0;
    if (!drained && this.prevFinalId && U > this.prevFinalId + 1) {
      // gap -> book is stale, ask for a fresh snapshot
      this.resyncs++; this.beginSync(); if (this.onResync) this.onResync();
      this.buffer.push(d); return;
    }
    for (const [p, q] of (d.b || [])) { const P = +p, Q = +q; if (Q === 0) this.bids.delete(P); else this.bids.set(P, Q); }
    for (const [p, q] of (d.a || [])) { const P = +p, Q = +q; if (Q === 0) this.asks.delete(P); else this.asks.set(P, Q); }
    this.prevFinalId = u; this.updates++;
    this._markShownAll();
  }

  _markShownAll() {
    const now = Date.now();
    for (const [P, Q] of this.bids) this._shown(P, Q, "bid", now);
    for (const [P, Q] of this.asks) this._shown(P, Q, "ask", now);
  }
  _shown(price, size, side, now) {
    let t = this.track.get(price);
    if (!t) { t = { maxShown: 0, executed: 0, hits: 0, side, refills: 0, lastShown: 0, t: now }; this.track.set(price, t); }
    if (size > t.lastShown * 1.5 && t.lastShown > 0) t.refills++;
    t.lastShown = size; if (size > t.maxShown) t.maxShown = size; t.side = side; t.t = now;
  }

  // ---------------------------------------------------------- trades ----
  applyTrade(price, qty, isSell) {
    const now = Date.now();
    let t = this.track.get(price);
    if (!t) { t = { maxShown: 0, executed: 0, hits: 0, side: isSell ? "bid" : "ask", refills: 0, lastShown: 0, t: now }; this.track.set(price, t); }
    t.executed += qty; t.hits++; t.t = now;
    this._detect(price, t, now);
  }
  _detect(price, t, now) {
    const c = this.cfg;
    if (t.maxShown > 0 && t.executed >= c.icebergExecMult * t.maxShown && t.executed >= c.icebergMinExec && t.refills >= 1)
      this._emit("iceberg", t.side, price, `Iceberg: ${t.executed.toFixed(2)} ejec. vs ${t.maxShown.toFixed(2)} visible`, now, price);
    const book = t.side === "bid" ? this.bids : this.asks;
    const resting = book.get(price) || 0;
    if (resting > 0 && this._isLarge(resting, t.side) && t.executed >= c.absorbExecMult * t.maxShown && t.maxShown > 0)
      this._emit("absorption", t.side, price, `Absorción: ${t.executed.toFixed(2)} absorbidos, ${resting.toFixed(2)} en pie`, now, price);
  }
  _isLarge(size, side) {
    const s = [...(side === "bid" ? this.bids : this.asks).values()].sort((a, b) => a - b);
    if (!s.length) return false;
    return size >= s[Math.min(Math.floor(s.length * this.cfg.absorbSizePct), s.length - 1)];
  }
  _emit(type, side, price, detail, t, key) {
    const last = this.signals[0];
    if (last && last.type === type && last.priceKey === key && t - last.t < 8000) return;
    this.signals.unshift({ type, side, price, detail, t, priceKey: key });
    this.signals = this.signals.slice(0, 60);
  }
  flagged(kind, sinceMs = 20000) {
    const now = Date.now(), s = new Set();
    for (const sig of this.signals) if (sig.type === kind && now - sig.t < sinceMs) s.add(sig.priceKey);
    return s;
  }

  // --------------------------------------------------------- queries ----
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
    return { bid: b, ask: a, imbalance: b + a > 0 ? (b - a) / (b + a) : 0, levels: this.bids.size + this.asks.size };
  }
  /** Aggregate resting size into price buckets (for heatmap). tick = bucket size. */
  bucketize(tick, lo, hi) {
    const m = new Map();
    const add = (p, q) => { if (p < lo || p > hi) return; const b = Math.round(p / tick); m.set(b, (m.get(b) || 0) + q); };
    for (const [p, q] of this.bids) add(p, q);
    for (const [p, q] of this.asks) add(p, q);
    return m;
  }
  prune(now = Date.now()) { for (const [p, t] of this.track) if (now - t.t > this.cfg.windowMs) this.track.delete(p); }
}
