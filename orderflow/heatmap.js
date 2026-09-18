/* Liquidity heatmap (Bookmap-style).

   Keeps a rolling set of columns, one per chart time-slot (candle). Each column
   is a snapshot of resting book liquidity aggregated into price buckets. The
   current (forming) column is refreshed from the live book; finished columns are
   frozen. Because past book state can't be reconstructed, the map builds forward
   from load — which is exactly how a live depth heatmap behaves. */

export class Heatmap {
  constructor() {
    this.cols = new Map();   // slotTime -> Map(bucketIdx -> size)
    this.max = 1;            // rolling max size for color scaling
    this.tick = 1;          // price per bucket (set by renderer)
  }

  /** capture the current book into the column for `slotTime`. */
  capture(slotTime, book, tick, lo, hi) {
    this.tick = tick;
    const map = book.bucketize(tick, lo, hi);
    this.cols.set(slotTime, { tick, map });
    let m = 0; for (const v of map.values()) if (v > m) m = v;
    // decay the rolling max slowly so bright spikes fade over time
    this.max = Math.max(m, this.max * 0.997, 1e-9);
  }

  column(slotTime) { return this.cols.get(slotTime); }
  /** a live column from the current book, not stored (used to backfill gaps). */
  live(book, tick, lo, hi) { return { tick, map: book.bucketize(tick, lo, hi) }; }

  prune(keepTimes) {
    const keep = new Set(keepTimes);
    for (const t of this.cols.keys()) if (!keep.has(t)) this.cols.delete(t);
  }

  /** viridis-ish heat color for a normalized value 0..1 (dark -> blue -> magenta -> orange -> white). */
  static color(t) {
    t = Math.max(0, Math.min(1, t));
    const stops = [
      [8, 12, 26], [26, 34, 92], [70, 34, 132], [140, 40, 120],
      [205, 70, 70], [240, 150, 45], [250, 220, 120], [255, 255, 235],
    ];
    const x = t * (stops.length - 1);
    const i = Math.floor(x), f = x - i;
    const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
    const r = Math.round(a[0] + (b[0] - a[0]) * f);
    const g = Math.round(a[1] + (b[1] - a[1]) * f);
    const bl = Math.round(a[2] + (b[2] - a[2]) * f);
    return `rgb(${r},${g},${bl})`;
  }
}
