/* Alerts engine: price-cross alerts and order-flow alerts (iceberg / absorption
   / stacked imbalance / CVD flip). Fires a toast, an optional WebAudio beep and,
   if permitted, a browser Notification. Persisted by the app via toJSON/load. */

let audioCtx = null;
function beep(kind = "up") {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = "sine";
    o.frequency.value = kind === "down" ? 420 : kind === "flow" ? 660 : 880;
    g.gain.setValueAtTime(0.001, audioCtx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.18, audioCtx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0008, audioCtx.currentTime + 0.35);
    o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.36);
  } catch {}
}

export class Alerts {
  constructor() {
    this.list = [];            // {id, kind:'price'|'flow', price?, dir?, flow?, note, active, hits}
    this.sound = true;
    this.notify = false;
    this.log = [];             // fired history {t, text, kind}
    this.onChange = null;      // UI refresh
    this.onFire = null;        // toast(text, kind)
    this._id = 1;
    this._lastPrice = null;
  }

  addPrice(price, note = "") {
    this.list.push({ id: this._id++, kind: "price", price, dir: null, note, active: true, hits: 0 });
    this._changed();
  }
  addFlow(flow, note = "") { // flow in {iceberg,absorption,stacked}
    this.list.push({ id: this._id++, kind: "flow", flow, note, active: true, hits: 0 });
    this._changed();
  }
  remove(id) { this.list = this.list.filter((a) => a.id !== id); this._changed(); }
  toggle(id) { const a = this.list.find((x) => x.id === id); if (a) { a.active = !a.active; this._changed(); } }
  clear() { this.list = []; this._changed(); }

  requestNotify() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") Notification.requestPermission().then((p) => { this.notify = p === "granted"; this._changed(); });
    else this.notify = Notification.permission === "granted";
  }

  /** call on every price update */
  onPrice(price, fmt) {
    if (this._lastPrice == null) { this._lastPrice = price; return; }
    for (const a of this.list) {
      if (a.kind !== "price" || !a.active) continue;
      const crossedUp = this._lastPrice < a.price && price >= a.price;
      const crossedDn = this._lastPrice > a.price && price <= a.price;
      if (crossedUp || crossedDn) {
        a.hits++;
        this._fire(`Precio cruzó ${fmt(a.price)} (${crossedUp ? "▲" : "▼"} ${fmt(price)})`, crossedUp ? "up" : "down");
      }
    }
    this._lastPrice = price;
  }

  /** call when a flow signal appears: kind in iceberg/absorption/stacked */
  onFlow(kind, detail) {
    for (const a of this.list) {
      if (a.kind !== "flow" || !a.active || a.flow !== kind) continue;
      a.hits++;
      this._fire(`${kind.toUpperCase()}: ${detail}`, "flow");
    }
  }

  _fire(text, kind) {
    this.log.unshift({ t: Date.now(), text, kind }); this.log = this.log.slice(0, 50);
    if (this.sound) beep(kind);
    if (this.notify && "Notification" in window && Notification.permission === "granted")
      try { new Notification("OrderFlow Pro", { body: text }); } catch {}
    if (this.onFire) this.onFire(text, kind);
    this._changed();
  }
  _changed() { if (this.onChange) this.onChange(); }

  toJSON() { return { list: this.list, sound: this.sound, notify: this.notify, id: this._id }; }
  load(o) { if (!o) return; this.list = o.list || []; this.sound = o.sound ?? true; this.notify = o.notify ?? false; this._id = o.id || (this.list.reduce((m, a) => Math.max(m, a.id), 0) + 1); }
}
