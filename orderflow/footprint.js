/* Footprint engine — order-flow data model + pro detections.
   Everything here is pure/stateless-ish logic shared by the seed loader
   and the live WebSocket feed. Rendering lives in app.js.

   Data model (one candle):
     {
       t, o, h, l, c,          // OHLC (ms open time + prices)
       levels: Map<idx, {bid, ask}>,   // idx = round(price / basetick)
       buy, sell, delta, vol,  // aggressor totals
       finished               // true once the candle has closed
     }
   bid = volume that hit the bid = aggressive SELL
   ask = volume that lifted the ask = aggressive BUY
*/

export const CFG = {
  imbalanceRatio: 3.0,   // diagonal bid/ask ratio to flag an imbalance (300%)
  imbalanceMinVol: 0,    // ignore tiny levels (set per-symbol at runtime)
  stackedMin: 3,         // consecutive imbalances => stacked (strong)
  absorbVolMult: 2.2,    // level vol vs candle avg-level vol to consider absorption
  absorbDeltaFrac: 0.6,  // how one-sided the absorbed aggression must be
  icebergVolMult: 3.0,   // level vol vs mean+σ outlier factor for iceberg
  icebergMinShare: 0.22, // level must hold >=22% of candle volume
};

// -------------------------------------------------------- candle helpers ----
export function newCandle(t, price) {
  return {
    t, o: price, h: price, l: price, c: price,
    levels: new Map(), buy: 0, sell: 0, delta: 0, vol: 0, finished: false,
  };
}

export function applyTrade(candle, price, qty, isSell, basetick) {
  const idx = Math.round(price / basetick);
  let cell = candle.levels.get(idx);
  if (!cell) { cell = { bid: 0, ask: 0 }; candle.levels.set(idx, cell); }
  if (isSell) { cell.bid += qty; candle.sell += qty; }
  else { cell.ask += qty; candle.buy += qty; }
  candle.delta = candle.buy - candle.sell;
  candle.vol = candle.buy + candle.sell;
  candle.c = price;
  if (price > candle.h) candle.h = price;
  if (price < candle.l) candle.l = price;
}

/** Build a candle from a compact seed row (rows = [[idx,bid,ask],...]). */
export function candleFromSeed(fp, basetick) {
  const c = newCandle(fp.t, fp.o);
  c.o = fp.o; c.h = fp.h; c.l = fp.l; c.c = fp.c;
  for (const [idx, bid, ask] of fp.rows) {
    c.levels.set(idx, { bid, ask });
  }
  c.buy = fp.buy; c.sell = fp.sell; c.delta = fp.delta; c.vol = fp.buy + fp.sell;
  c.finished = true;
  return c;
}

/** Sorted [idx, cell] pairs, high price first. */
export function sortedLevels(candle) {
  return [...candle.levels.entries()].sort((a, b) => b[0] - a[0]);
}

export function pocIdx(candle) {
  let best = null, bestV = -1;
  for (const [idx, cell] of candle.levels) {
    const v = cell.bid + cell.ask;
    if (v > bestV) { bestV = v; best = idx; }
  }
  return best;
}

// ------------------------------------------------------------ detections ----
/**
 * Diagonal imbalances (Bid/Ask footprint standard):
 *   BUY  imbalance at idx  : ask[idx]  >= ratio * bid[idx-1]   (demand stacking up)
 *   SELL imbalance at idx  : bid[idx]  >= ratio * ask[idx+1]   (supply stacking down)
 * Returns Map<idx, 'buy'|'sell'> plus stacked runs (>= stackedMin in a row).
 */
export function imbalances(candle, cfg = CFG) {
  const flags = new Map();
  const g = (idx, k) => { const c = candle.levels.get(idx); return c ? c[k] : 0; };
  for (const [idx, cell] of candle.levels) {
    const below = g(idx - 1, "bid");
    const above = g(idx + 1, "ask");
    if (cell.ask >= cfg.imbalanceMinVol &&
        cell.ask >= cfg.imbalanceRatio * Math.max(below, 1e-9) && below >= 0) {
      if (cell.ask > 0 && (below === 0 || cell.ask / below >= cfg.imbalanceRatio)) {
        flags.set(idx, "buy");
      }
    }
    if (cell.bid >= cfg.imbalanceMinVol &&
        cell.bid > 0 && (above === 0 || cell.bid / Math.max(above, 1e-9) >= cfg.imbalanceRatio)) {
      // sell imbalance wins the cell only if it isn't already a stronger buy
      if (!flags.has(idx)) flags.set(idx, "sell");
    }
  }
  // stacked runs over consecutive tick indices with the same direction
  const idxs = [...candle.levels.keys()].sort((a, b) => a - b);
  const stacks = [];
  let run = [];
  const flush = () => {
    if (run.length >= cfg.stackedMin) {
      stacks.push({
        dir: flags.get(run[0]),
        from: run[0], to: run[run.length - 1], count: run.length,
      });
    }
    run = [];
  };
  for (let i = 0; i < idxs.length; i++) {
    const idx = idxs[i];
    const dir = flags.get(idx);
    const contiguous = run.length === 0 || idx === run[run.length - 1] + 1;
    if (dir && contiguous && (run.length === 0 || flags.get(run[0]) === dir)) {
      run.push(idx);
    } else {
      flush();
      if (dir) run = [idx];
    }
  }
  flush();
  return { flags, stacks };
}

/** Per-candle level statistics used by absorption / iceberg. */
function levelStats(candle) {
  const vols = [];
  for (const cell of candle.levels.values()) vols.push(cell.bid + cell.ask);
  const n = vols.length || 1;
  const mean = vols.reduce((a, b) => a + b, 0) / n;
  const variance = vols.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
  return { mean, std: Math.sqrt(variance), max: Math.max(0, ...vols) };
}

/**
 * Absorption: heavy one-sided aggression at a candle extreme that fails to move
 * price through it (the passive side absorbs). We flag the extreme level when
 * its volume is a strong outlier AND aggression there is lopsided AND that
 * aggression's direction did NOT win the bar (price rejected).
 * Returns [{idx, side, vol, delta}] (side = side being absorbed).
 */
export function absorption(candle, cfg = CFG) {
  const out = [];
  if (candle.levels.size < 3) return out;
  const st = levelStats(candle);
  const bodyUp = candle.c >= candle.o;
  for (const [idx, cell] of candle.levels) {
    const v = cell.bid + cell.ask;
    if (v < cfg.absorbVolMult * st.mean) continue;
    const d = cell.ask - cell.bid;
    const oneSided = Math.abs(d) >= cfg.absorbDeltaFrac * v;
    if (!oneSided) continue;
    // aggressive BUY absorbed near the top but candle closed down -> supply held
    if (d > 0 && !bodyUp) out.push({ idx, side: "buy", vol: v, delta: d });
    // aggressive SELL absorbed near the bottom but candle closed up -> demand held
    if (d < 0 && bodyUp) out.push({ idx, side: "sell", vol: v, delta: d });
  }
  // keep the single strongest absorption per candle to avoid noise
  out.sort((a, b) => b.vol - a.vol);
  return out.slice(0, 1);
}

/**
 * Iceberg (approximation without L2 book): a single price level that soaks up a
 * disproportionate share of the candle's volume — a statistical outlier vs the
 * other levels — which typically means a hidden refilling limit order.
 * Returns [{idx, vol, share, side}].
 */
export function icebergs(candle, cfg = CFG) {
  const out = [];
  if (candle.levels.size < 4 || candle.vol <= 0) return out;
  const st = levelStats(candle);
  const threshold = st.mean + cfg.icebergVolMult * st.std;
  for (const [idx, cell] of candle.levels) {
    const v = cell.bid + cell.ask;
    const share = v / candle.vol;
    if (v >= threshold && share >= cfg.icebergMinShare) {
      out.push({
        idx, vol: v, share,
        side: cell.bid >= cell.ask ? "bid" : "ask",  // passive side likely resting
      });
    }
  }
  out.sort((a, b) => b.vol - a.vol);
  return out.slice(0, 2);
}

/** Run all detections for a candle; returns a compact signals object. */
export function analyze(candle, cfg = CFG) {
  const imb = imbalances(candle, cfg);
  return {
    flags: imb.flags,
    stacks: imb.stacks,
    absorption: absorption(candle, cfg),
    icebergs: icebergs(candle, cfg),
    poc: pocIdx(candle),
  };
}
