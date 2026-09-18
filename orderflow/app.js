/* Order Flow Terminal — candle+delta view (reference style) + footprint mode,
   with live L2 order book (DOM ladder + on-chart depth histogram) and real
   iceberg / absorption detection from the book. */

import { CFG, newCandle, applyTrade, candleFromSeed, analyze } from "./footprint.js";
import { OrderBook } from "./orderbook.js";

const $ = (id) => document.getElementById(id);
const canvas = $("chart");
const ctx = canvas.getContext("2d");

const C = {
  bg: "#05070a", grid: "#0f141c", gridSoft: "#0b0f15", axis: "#66717f",
  up: "#e8912a", upWick: "#b06f22", down: "#e0453e", downWick: "#a5332e",
  buy: "#23c176", sell: "#f0524a",
  profBid: "#3d6bd6", profAsk: "#c0392b",
  poc: "#ff4d3d", vaLine: "#cfd6df", vaFill: "rgba(120,140,180,.05)",
  vwap: "#4aa3ff", ice: "#35c9e0", absorb: "#c77dff", zone: "rgba(120,110,220,.45)",
  depthBid: "rgba(35,193,118,.55)", depthAsk: "rgba(240,82,74,.55)",
};

const state = {
  mode: "chart",
  symbol: "BTCUSDT", interval: "1m", basetick: 1, intervalMs: 60000,
  ohlc: [],            // full OHLC+delta (chart mode)
  candles: [],         // footprint candles (footprint mode + detection)
  va: { vpoc: 0, vah: 0, val: 0 }, profile: [], priceLow: 0, priceHigh: 0,
  book: new OrderBook(),
  ws: null, wsTries: 0, pollTimer: null, pruneTimer: null,
  dirty: false, hover: -1,
  toggles: { profile: true, vwap: true, depth: true, bubbles: true },
  fpSignals: [], layout: null,
};

// helpers
const nf = (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (n, d = 2) => (n >= 0 ? "+" : "") + nf(n, d);
const volFmt = (v) => v >= 1000 ? (v / 1000).toFixed(1) + "k" : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
const hhmm = (t) => { const d = new Date(t); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
function setConn(cls, msg) { $("conn").className = "conn " + cls; if (msg) $("status").textContent = msg; }
function markDirty() { if (state.dirty) return; state.dirty = true; requestAnimationFrame(() => { state.dirty = false; draw(); updateLadder(); }); }

// ---------------------------------------------------------------- seed ----
async function loadSeed() {
  state.symbol = $("symbol").value; state.interval = $("interval").value;
  const n = $("candles").value;
  setConn("wait", "Cargando datos reales…");
  try {
    const fp = state.mode === "footprint" ? Math.min(40, parseInt(n, 10)) : 18;
    const [seedR, depthR] = await Promise.all([
      fetch(`/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=120&fp=${fp}`),
      fetch(`/api/depth?symbol=${state.symbol}&limit=50`),
    ]);
    const d = await seedR.json();
    if (d.error) throw new Error(d.error);
    state.basetick = d.basetick; state.intervalMs = d.intervalMs;
    state.ohlc = d.candles;
    state.va = { vpoc: d.vpoc, vah: d.vah, val: d.val };
    state.profile = d.profile; state.priceLow = d.priceLow; state.priceHigh = d.priceHigh;
    state.candles = d.footprints.map((f) => candleFromSeed(f, d.basetick));
    rebuildFpSignals();
    try { const dep = await depthR.json(); if (!dep.error) state.book.seed(dep); } catch {}
    $("hdr-symbol").textContent = `${state.symbol} · ${state.interval}`;
    updateHeader(d.lastPrice); updateLive();
    resize(); updateLadder();
    setConn("wait", "Listo · conectando stream…");
    connectWS();
  } catch (e) { setConn("off", "Error: " + e.message); }
}

// ------------------------------------------------------ live websocket ----
function wsUrls() {
  const s = state.symbol.toLowerCase();
  const streams = `${s}@aggTrade/${s}@kline_${state.interval}/${s}@depth20@100ms`;
  return [
    `wss://data-stream.binance.vision/stream?streams=${streams}`,
    `wss://stream.binance.com:9443/stream?streams=${streams}`,
  ];
}
function connectWS() {
  closeWS();
  const url = wsUrls()[state.wsTries % 2];
  let opened = false, ws;
  try { ws = new WebSocket(url); } catch { return startPolling(); }
  state.ws = ws;
  const failTimer = setTimeout(() => { if (!opened) { try { ws.close(); } catch {} } }, 4500);
  ws.onopen = () => { opened = true; state.wsTries = 0; clearTimeout(failTimer); stopPolling(); setConn("on", "En vivo · WebSocket + L2"); ensurePrune(); };
  ws.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    const d = m.data || m;
    if (d.e === "aggTrade") onAggTrade(d);
    else if (d.e === "kline") onKline(d.k);
    else if (d.bids || d.b || d.asks || d.a) onDepth(d);
  };
  ws.onclose = () => {
    clearTimeout(failTimer);
    if (!opened) state.wsTries++;
    if (state.wsTries >= 2 && !opened) { setConn("off", "WS bloqueado · usando REST"); return startPolling(); }
    setConn("wait", "Reconectando…"); setTimeout(connectWS, 1200);
  };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
function closeWS() { if (state.ws) { try { state.ws.onclose = null; state.ws.close(); } catch {} state.ws = null; } }
function ensurePrune() { if (!state.pruneTimer) state.pruneTimer = setInterval(() => state.book.prune(), 5000); }

const bucketOf = (t) => Math.floor(t / state.intervalMs) * state.intervalMs;

function ensureFpCandle(bucketT, price) {
  const last = state.candles[state.candles.length - 1];
  if (last && last.t === bucketT) return last;
  if (last && bucketT > last.t) last.finished = true;
  const c = newCandle(bucketT, price);
  state.candles.push(c);
  if (state.candles.length > 60) state.candles.shift();
  return c;
}
function ensureOhlc(bucketT, price) {
  const last = state.ohlc[state.ohlc.length - 1];
  if (last && last.t === bucketT) return last;
  const c = { t: bucketT, o: price, h: price, l: price, c: price, v: 0, delta: 0 };
  state.ohlc.push(c);
  if (state.ohlc.length > 300) state.ohlc.shift();
  return c;
}

function onAggTrade(d) {
  const price = +d.p, qty = +d.q, isSell = d.m;
  applyTrade(ensureFpCandle(bucketOf(d.T), price), price, qty, isSell, state.basetick);
  state.book.applyTrade(price, qty, isSell);
  updateHeader(price); updateLive();
  markDirty();
}
function onKline(k) {
  const c = ensureOhlc(+k.t, +k.o);
  c.o = +k.o; c.h = +k.h; c.l = +k.l; c.c = +k.c; c.v = +k.v;
  c.delta = 2 * (+k.V) - (+k.v);   // taker-buy*2 - vol
  if (k.x) rebuildFpSignals();
  updateHeader(+k.c); markDirty();
}
function onDepth(d) { state.book.applyDepth(d); markDirty(); }

// -------------------------------------------------- REST polling fallback -
function startPolling() {
  if (state.pollTimer) return;
  const tick = async () => {
    try {
      const fp = state.mode === "footprint" ? Math.min(40, parseInt($("candles").value, 10)) : 18;
      const [s, dep] = await Promise.all([
        fetch(`/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=120&fp=${fp}`).then((r) => r.json()),
        fetch(`/api/depth?symbol=${state.symbol}&limit=50`).then((r) => r.json()),
      ]);
      if (!s.error) {
        state.ohlc = s.candles; state.va = { vpoc: s.vpoc, vah: s.vah, val: s.val };
        state.profile = s.profile; state.priceLow = s.priceLow; state.priceHigh = s.priceHigh;
        state.candles = s.footprints.map((f) => candleFromSeed(f, s.basetick));
        rebuildFpSignals(); updateHeader(s.lastPrice); updateLive();
      }
      if (!dep.error) state.book.seed(dep);
      markDirty();
    } catch {}
  };
  state.pollTimer = setInterval(tick, 4000); tick();
}
function stopPolling() { if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; } }

// -------------------------------------------------- footprint detection ---
function aggregate(candle, k) {
  if (k <= 1) return candle;
  const levels = new Map();
  for (const [idx, cell] of candle.levels) {
    const di = Math.floor(idx / k);
    let c = levels.get(di); if (!c) { c = { bid: 0, ask: 0 }; levels.set(di, c); }
    c.bid += cell.bid; c.ask += cell.ask;
  }
  return { ...candle, levels };
}
function sigCfg(c) {
  const vols = [...c.levels.values()].map((x) => x.bid + x.ask);
  const mean = vols.reduce((a, b) => a + b, 0) / (vols.length || 1);
  return { ...CFG, imbalanceMinVol: mean * 0.5 };
}
function rebuildFpSignals() {
  const k = state.layout && state.layout.k ? state.layout.k : 1;
  const feed = [];
  for (const base of state.candles) {
    const c = aggregate(base, k), a = analyze(c, sigCfg(c)), dt = state.basetick * k;
    for (const st of a.stacks) feed.push({ src: "FP", kind: st.dir, price: (st.dir === "buy" ? st.to : st.from) * dt, detail: `Stacked ${st.dir === "buy" ? "compra" : "venta"} ×${st.count}`, t: base.t });
  }
  state.fpSignals = feed;
  renderSignals();
}

// ------------------------------------------------------------ header/live -
function updateHeader(price) {
  $("hdr-price").textContent = nf(price, 2);
  const first = state.ohlc.length ? state.ohlc[Math.max(0, state.ohlc.length - 60)].o : price;
  const chg = ((price - first) / first) * 100;
  const el = $("hdr-chg"); el.textContent = sgn(chg, 2) + "%"; el.className = "hchg " + (chg >= 0 ? "pos" : "neg");
}
function updateLive() {
  const last = state.ohlc[state.ohlc.length - 1];
  if (last) {
    const de = $("l-delta"); de.textContent = sgn(last.delta, 1); de.className = last.delta >= 0 ? "pos" : "neg";
    const buy = (last.v + last.delta) / 2, sell = last.v - buy;
    $("l-bs").textContent = `${nf(buy, 1)} / ${nf(sell, 1)}`;
  }
  const cvd = state.ohlc.slice(-60).reduce((a, x) => a + x.delta, 0);
  const cv = $("l-cvd"); cv.textContent = sgn(cvd, 0); cv.className = cvd >= 0 ? "pos" : "neg";
  $("l-va").textContent = `${nf(state.va.vpoc, 0)} / ${nf(state.va.vah, 0)} / ${nf(state.va.val, 0)}`;
  const t = state.book.totals();
  $("l-depth").textContent = `${nf(t.bid, 1)} / ${nf(t.ask, 1)}`;
  const im = $("ob-imb");
  if (t.bid + t.ask > 0) { im.textContent = (t.imbalance >= 0 ? "▲ " : "▼ ") + nf(Math.abs(t.imbalance) * 100, 0) + "%"; im.className = "imb " + (t.imbalance >= 0 ? "pos" : "neg"); }
}

// ---------------------------------------------------------- DOM ladder ----
function updateLadder() {
  const el = $("ladder");
  const bids = [...state.book.bids.entries()].sort((a, b) => b[0] - a[0]);
  const asks = [...state.book.asks.entries()].sort((a, b) => b[0] - a[0]);
  if (!bids.length && !asks.length) { el.innerHTML = '<div class="sig-empty">Esperando order book…</div>'; return; }
  const maxSz = Math.max(1e-9, ...bids.map((x) => x[1]), ...asks.map((x) => x[1]));
  const ice = state.book.flagged("iceberg"), abs = state.book.flagged("absorption");
  const topAsks = asks.slice(-10);    // 10 asks nearest the spread (low->high, shown top-down high->low)
  const topBids = bids.slice(0, 10);
  const price2 = state.symbol.includes("BTC") ? 2 : 3;
  const row = (p, q, side) => {
    const w = Math.min(100, (q / maxSz) * 100);
    const flag = ice.has(p) ? '<span class="lad-flag" title="iceberg">❄</span>'
      : abs.has(p) ? '<span class="lad-flag abs" title="absorción">◆</span>' : "";
    const bidCell = side === "bid"
      ? `<div class="sz b" style="background:linear-gradient(270deg,var(--bidfill) ${w}%,transparent ${w}%)">${volFmt(q)}${flag}</div>`
      : `<div class="sz"></div>`;
    const askCell = side === "ask"
      ? `<div class="sz a" style="background:linear-gradient(90deg,var(--askfill) ${w}%,transparent ${w}%)">${flag}${volFmt(q)}</div>`
      : `<div class="sz"></div>`;
    return `<div class="lad-row ${side}">${bidCell}<div class="price">${nf(p, price2)}</div>${askCell}</div>`;
  };
  const best = state.book.best();
  const spread = best.bid && best.ask ? (best.ask - best.bid) : 0;
  el.innerHTML =
    topAsks.map(([p, q]) => row(p, q, "ask")).join("") +
    `<div class="lad-row spread"><div class="sz"></div><div class="price">↕ ${nf(spread, price2)}</div><div class="sz"></div></div>` +
    topBids.map(([p, q]) => row(p, q, "bid")).join("");
}

// ------------------------------------------------------------- geometry ---
const AX_W = 62, TIME_H = 34, TOP = 10, DEPTH_W = 70;

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw();
}

function computeLayout() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const isFp = state.mode === "footprint";
  const src = isFp ? state.candles : state.ohlc;
  const n = Math.min(src.length, parseInt($("candles").value, 10));
  const vis = src.slice(src.length - n);
  if (!vis.length) return null;

  const profW = state.toggles.profile ? (isFp ? 66 : 140) : 6;
  const depthW = state.toggles.depth ? DEPTH_W : 0;
  const plotL = profW;
  const plotR = w - AX_W - depthW;
  const plotT = TOP;
  const plotB = h - TIME_H - (isFp ? 60 : 0);

  let lo = Infinity, hi = -Infinity;
  for (const c of vis) { if (c.l < lo) lo = c.l; if (c.h > hi) hi = c.h; }
  if (!isFp) {  // include VA + book in range for context
    lo = Math.min(lo, state.va.val); hi = Math.max(hi, state.va.vah);
  }
  const pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
  if (!(hi > lo)) hi = lo + state.basetick * 10;

  const y = (p) => plotB - ((p - lo) / (hi - lo)) * (plotB - plotT);
  const colW = (plotR - plotL) / n;

  const L = { w, h, isFp, vis, n, lo, hi, plotL, plotR, plotT, plotB, depthW, profW, y, colW };
  if (isFp) {
    const availH = plotB - plotT;
    const desiredRows = Math.min(70, Math.max(8, Math.floor(availH / 13)));
    const k = Math.max(1, Math.ceil(((hi - lo) / state.basetick) / desiredRows));
    const dTick = state.basetick * k;
    L.k = k; L.dTick = dTick;
    L.rowLo = Math.floor(lo / dTick); L.rowHi = Math.ceil(hi / dTick);
    L.rowH = availH / Math.max(1, L.rowHi - L.rowLo);
    L.rowY = (di) => plotB - (di - L.rowLo) * L.rowH;
  }
  return L;
}

// ---------------------------------------------------------------- draw ----
function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h); ctx.fillStyle = C.bg; ctx.fillRect(0, 0, w, h);
  const L = computeLayout(); state.layout = L;
  if (!L) return;
  drawValueArea(L);
  drawGrid(L);
  if (L.isFp) { drawFpProfile(L); drawClusters(L); }
  else { if (state.toggles.profile) drawProfile(L); drawCandles(L); if (state.toggles.vwap) drawVWAP(L); if (state.toggles.bubbles) drawBubbles(L); }
  drawLevels(L);
  if (state.toggles.depth) drawDepthHistogram(L);
  drawPriceAxis(L);
  drawTimeAxis(L);
  drawLastPrice(L);
  if (!L.isFp) drawFooter(L);
}

function drawGrid(L) {
  ctx.strokeStyle = C.gridSoft; ctx.lineWidth = 1;
  const step = Math.max(1, Math.floor(L.n / 12));
  for (let i = 0; i <= L.n; i += step) {
    const x = Math.round(L.plotL + i * L.colW) + 0.5;
    ctx.beginPath(); ctx.moveTo(x, L.plotT); ctx.lineTo(x, L.plotB); ctx.stroke();
  }
}
function drawValueArea(L) {
  const yH = L.y(state.va.vah), yL = L.y(state.va.val);
  ctx.fillStyle = C.vaFill; ctx.fillRect(L.plotL, Math.min(yH, yL), L.plotR - L.plotL, Math.abs(yL - yH));
}

// profile (chart mode): blue above POC, red below — like the reference
function drawProfile(L) {
  if (!state.profile.length) return;
  const inRange = state.profile.filter((p) => p.price >= L.lo && p.price <= L.hi);
  const maxV = Math.max(1, ...inRange.map((p) => p.vol));
  const bh = Math.max(1, (L.plotB - L.plotT) / (inRange.length || 1) - 0.5);
  for (const p of state.profile) {
    if (p.price < L.lo || p.price > L.hi) continue;
    const yy = L.y(p.price);
    const wgt = (p.vol / maxV) * (L.profW - 8);
    ctx.fillStyle = p.price >= state.va.vpoc ? C.profBid : C.profAsk;
    ctx.globalAlpha = 0.55;
    ctx.fillRect(L.profW - wgt, yy - bh / 2, wgt, bh);
    ctx.globalAlpha = 1;
  }
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.profW + .5, L.plotT); ctx.lineTo(L.profW + .5, L.plotB); ctx.stroke();
}

function drawCandles(L) {
  const bw = Math.max(1.5, Math.min(11, L.colW * 0.62));
  L.vis.forEach((c, i) => {
    const x = L.plotL + i * L.colW + L.colW / 2;
    const up = c.c >= c.o;
    ctx.strokeStyle = up ? C.upWick : C.downWick; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, L.y(c.h)); ctx.lineTo(x, L.y(c.l)); ctx.stroke();
    ctx.fillStyle = up ? C.up : C.down;
    const top = Math.min(L.y(c.o), L.y(c.c)), hgt = Math.max(1, Math.abs(L.y(c.c) - L.y(c.o)));
    ctx.fillRect(x - bw / 2, top, bw, hgt);
    if (i === state.hover) { ctx.strokeStyle = "rgba(255,255,255,.5)"; ctx.strokeRect(x - bw / 2 - 1, top - 1, bw + 2, hgt + 2); }
  });
}

function drawVWAP(L) {
  let pv = 0, vv = 0; const pts = [];
  for (const c of L.vis) { const tp = (c.h + c.l + c.c) / 3; pv += tp * c.v; vv += c.v; pts.push(vv ? pv / vv : c.c); }
  ctx.strokeStyle = C.vwap; ctx.lineWidth = 1.6; ctx.beginPath();
  pts.forEach((v, i) => { const x = L.plotL + i * L.colW + L.colW / 2; i ? ctx.lineTo(x, L.y(v)) : ctx.moveTo(x, L.y(v)); });
  ctx.stroke();
  ctx.fillStyle = C.vwap; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "left";
  ctx.fillText("VWAP", L.plotL + 4, L.y(pts[pts.length - 1]) - 4);
}

function drawBubbles(L) {
  const maxAbs = Math.max(1, ...L.vis.map((c) => Math.abs(c.delta)));
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  L.vis.forEach((c, i) => {
    if (!c.delta) return;
    const x = L.plotL + i * L.colW + L.colW / 2;
    const yy = L.y(c.c);
    const r = 7 + (Math.abs(c.delta) / maxAbs) * 17;
    ctx.beginPath(); ctx.fillStyle = c.delta >= 0 ? C.buy : C.sell; ctx.globalAlpha = 0.92;
    ctx.arc(x, yy, r, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
    if (r >= 10) {
      ctx.fillStyle = "#fff"; ctx.font = `bold ${Math.min(12, r * 0.85)}px ui-monospace, monospace`;
      ctx.fillText(String(Math.round(Math.abs(c.delta))), x, yy + 0.5);
    }
  });
  ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
}

// ------- footprint mode (compact reuse) -------
function drawFpProfile(L) {
  const prof = new Map(); let maxV = 0;
  for (const base of L.vis) { const c = aggregate(base, L.k);
    for (const [di, cell] of c.levels) { let p = prof.get(di); if (!p) { p = { bid: 0, ask: 0 }; prof.set(di, p); } p.bid += cell.bid; p.ask += cell.ask; maxV = Math.max(maxV, p.bid + p.ask); } }
  maxV = maxV || 1;
  for (const [di, cell] of prof) {
    const yTop = L.rowY(di + 1), hgt = Math.max(1, L.rowH - .5);
    const bw = (cell.ask / maxV) * (L.profW - 6), sw = (cell.bid / maxV) * (L.profW - 6);
    ctx.globalAlpha = .5; ctx.fillStyle = C.buy; ctx.fillRect(L.profW - bw, yTop, bw, hgt);
    ctx.fillStyle = C.sell; ctx.fillRect(L.profW - bw - sw, yTop, sw, hgt); ctx.globalAlpha = 1;
  }
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.profW + .5, L.plotT); ctx.lineTo(L.profW + .5, L.plotB); ctx.stroke();
}
function drawClusters(L) {
  const showNums = L.colW >= 44 && L.rowH >= 10;
  ctx.textBaseline = "middle"; ctx.font = `${Math.max(7.5, Math.min(10, L.rowH - 2))}px ui-monospace, monospace`;
  L.vis.forEach((base, ci) => {
    const c = aggregate(base, L.k), a = analyze(c, sigCfg(c));
    const x0 = L.plotL + ci * L.colW, midX = x0 + L.colW / 2;
    let cmax = 1; for (const cell of c.levels.values()) cmax = Math.max(cmax, cell.bid + cell.ask);
    const up = c.c >= c.o; ctx.globalAlpha = .5; ctx.strokeStyle = up ? C.up : C.down;
    ctx.beginPath(); ctx.moveTo(midX, L.y(c.h)); ctx.lineTo(midX, L.y(c.l)); ctx.stroke(); ctx.globalAlpha = 1;
    for (const [di, cell] of c.levels) {
      const yTop = L.rowY(di + 1), yMid = yTop + L.rowH / 2; if (yTop > L.plotB || yTop + L.rowH < L.plotT) continue;
      const half = (L.colW - 2) / 2;
      ctx.fillStyle = C.sell; ctx.globalAlpha = .1 + .28 * (cell.bid / cmax); ctx.fillRect(x0 + 1, yTop + .5, half, L.rowH - 1);
      ctx.fillStyle = C.buy; ctx.globalAlpha = .1 + .28 * (cell.ask / cmax); ctx.fillRect(midX, yTop + .5, half, L.rowH - 1); ctx.globalAlpha = 1;
      const dir = a.flags.get(di);
      if (dir === "buy") { ctx.strokeStyle = C.buy; ctx.lineWidth = 1.4; ctx.strokeRect(midX + .5, yTop + 1, half - 1, L.rowH - 2); }
      else if (dir === "sell") { ctx.strokeStyle = C.sell; ctx.lineWidth = 1.4; ctx.strokeRect(x0 + 1.5, yTop + 1, half - 1, L.rowH - 2); }
      if (showNums) {
        ctx.textAlign = "right"; ctx.fillStyle = cell.bid > 0 ? "#ff9c96" : "#39424f"; ctx.fillText(volFmt(cell.bid), midX - 3, yMid);
        ctx.textAlign = "left"; ctx.fillStyle = cell.ask > 0 ? "#7ff0b4" : "#39424f"; ctx.fillText(volFmt(cell.ask), midX + 3, yMid);
      }
    }
    for (const st of a.stacks) { const yA = L.rowY(st.to + 1), yB = L.rowY(st.from); ctx.strokeStyle = st.dir === "buy" ? C.buy : C.sell; ctx.lineWidth = 2.5; const bx = st.dir === "buy" ? x0 + L.colW - 2 : x0 + 2; ctx.beginPath(); ctx.moveTo(bx, yA); ctx.lineTo(bx, yB); ctx.stroke(); }
    if (a.poc != null) { const yTop = L.rowY(a.poc + 1); ctx.strokeStyle = C.poc; ctx.lineWidth = 1; ctx.strokeRect(x0 + 1, yTop + .5, L.colW - 2, L.rowH - 1); }
  });
  ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
  drawFpDeltaStrip(L);
}
function drawFpDeltaStrip(L) {
  const y0 = L.plotB, yH = 58; ctx.fillStyle = "#070a0e"; ctx.fillRect(L.plotL, y0, L.plotR - L.plotL, yH);
  let maxAbs = 1; for (const c of L.vis) maxAbs = Math.max(maxAbs, Math.abs(c.delta));
  const mid = y0 + yH * 0.5; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "center";
  L.vis.forEach((c, ci) => { const x0 = L.plotL + ci * L.colW; const bh = (Math.abs(c.delta) / maxAbs) * (yH * .38);
    ctx.fillStyle = c.delta >= 0 ? C.buy : C.sell;
    if (c.delta >= 0) ctx.fillRect(x0 + 2, mid - bh, L.colW - 4, bh); else ctx.fillRect(x0 + 2, mid, L.colW - 4, bh);
    if (L.colW >= 30) { ctx.fillStyle = c.delta >= 0 ? "#7ff0b4" : "#ff9c96"; ctx.fillText(String(Math.round(c.delta)), x0 + L.colW / 2, y0 + yH - 5); } });
  ctx.fillStyle = C.axis; ctx.textAlign = "left"; ctx.fillText("Δ", 6, y0 + 12);
}

// on-chart L2 depth histogram (current resting liquidity by price)
function drawDepthHistogram(L) {
  const x0 = L.plotR, ww = L.depthW;
  ctx.fillStyle = "#070a0e"; ctx.fillRect(x0, L.plotT, ww, L.plotB - L.plotT);
  const bids = [...state.book.bids.entries()], asks = [...state.book.asks.entries()];
  const maxSz = Math.max(1, ...bids.map((x) => x[1]), ...asks.map((x) => x[1]));
  const ice = state.book.flagged("iceberg"), abs = state.book.flagged("absorption");
  const bar = (p, q, color) => {
    if (p < L.lo || p > L.hi) return;
    const yy = L.y(p), bw = (q / maxSz) * (ww - 4);
    ctx.fillStyle = color; ctx.fillRect(x0 + 1, yy - 1.5, bw, 3);
    if (ice.has(p)) { ctx.fillStyle = C.ice; ctx.fillRect(x0 + 1, yy - 1.5, bw, 3); }
    else if (abs.has(p)) { ctx.fillStyle = C.absorb; ctx.fillRect(x0 + 1, yy - 1.5, bw, 3); }
  };
  for (const [p, q] of bids) bar(p, q, C.depthBid);
  for (const [p, q] of asks) bar(p, q, C.depthAsk);
  ctx.fillStyle = C.axis; ctx.font = "8px ui-monospace, monospace"; ctx.textAlign = "left";
  ctx.fillText("L2", x0 + 3, L.plotT + 9);
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x0 + .5, L.plotT); ctx.lineTo(x0 + .5, L.plotB); ctx.stroke();
}

function levelLine(L, price, color, label, dash) {
  const yy = Math.round(L.y(price)) + .5; if (yy < L.plotT || yy > L.plotB) return;
  ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(dash ? [6, 4] : []);
  ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = color; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.fillText(label, L.plotL + 4, yy - 3);
}
function drawLevels(L) {
  levelLine(L, state.va.vah, C.vaLine, "VAH", true);
  levelLine(L, state.va.val, C.vaLine, "VAL", true);
  levelLine(L, state.va.vpoc, C.poc, "vPOC", false);
}
function drawPriceAxis(L) {
  ctx.fillStyle = C.axis; ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "left";
  const steps = 8, xLabel = L.plotR + L.depthW + 5;
  for (let i = 0; i <= steps; i++) {
    const p = L.lo + (i / steps) * (L.hi - L.lo), yy = Math.round(L.y(p));
    if (yy < L.plotT || yy > L.plotB) continue;
    ctx.strokeStyle = C.gridSoft; ctx.beginPath(); ctx.moveTo(L.plotL, yy + .5); ctx.lineTo(L.plotR, yy + .5); ctx.stroke();
    ctx.fillStyle = C.axis; ctx.fillText(nf(p, p > 1000 ? 0 : 2), xLabel, yy + 3);
  }
}
function drawTimeAxis(L) {
  ctx.fillStyle = C.axis; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "center";
  const y = L.plotB + 13, step = Math.ceil(L.n / 9);
  L.vis.forEach((c, ci) => { if (ci % step) return; ctx.fillText(hhmm(c.t), L.plotL + ci * L.colW + L.colW / 2, y); });
}
function drawLastPrice(L) {
  const src = L.isFp ? state.candles : state.ohlc; const last = src[src.length - 1]; if (!last) return;
  const yy = Math.round(L.y(last.c)) + .5; if (yy < L.plotT || yy > L.plotB) return;
  const up = last.c >= last.o;
  ctx.strokeStyle = up ? C.up : C.down; ctx.setLineDash([2, 2]); ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR + L.depthW, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = up ? C.up : C.down; ctx.fillRect(L.plotR + L.depthW, yy - 8, AX_W, 16);
  ctx.fillStyle = "#07090c"; ctx.font = "bold 10px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.fillText(nf(last.c, 2), L.plotR + L.depthW + 4, yy + 3);
}
function drawFooter(L) {
  const vis = L.vis; const lots = vis.reduce((a, c) => a + c.v, 0); const delta = vis.reduce((a, c) => a + c.delta, 0);
  ctx.font = "11px ui-monospace, monospace"; ctx.textAlign = "center";
  const cx = (L.plotL + L.plotR) / 2, y = L.plotB + 28;
  ctx.fillStyle = C.axis; ctx.fillText(`${nf(lots, 2)} Lots   |   `, cx - 34, y);
  ctx.textAlign = "left"; ctx.fillStyle = delta >= 0 ? C.buy : C.sell;
  ctx.fillText(`Δ=${sgn(delta, 0)}`, cx + 30, y);
  ctx.textAlign = "left";
}

// ------------------------------------------------------------- signals ----
function renderSignals() {
  const l2 = state.book.signals.map((s) => ({ src: "L2", kind: s.type, price: s.price, detail: s.detail, t: s.t }));
  const merged = [...l2, ...state.fpSignals].sort((a, b) => b.t - a.t).slice(0, 30);
  const el = $("sig-list"); $("sig-count").textContent = merged.length;
  if (!merged.length) { el.innerHTML = '<div class="sig-empty">Sin señales aún… (llegan con el stream en vivo)</div>'; return; }
  const icons = { buy: "▲", sell: "▼", iceberg: "❄", absorption: "◆" };
  el.innerHTML = merged.map((s) => {
    const cls = s.kind === "buy" ? "buy" : s.kind === "sell" ? "sell" : s.kind;
    const tag = s.src === "L2" ? '<b style="color:var(--vwap)">L2</b> ' : "";
    return `<div class="sig ${cls}"><div class="ic">${icons[s.kind] || "•"}</div>
      <div class="tx">${tag}${s.detail}<small>${nf(s.price, 1)}</small></div>
      <div class="tm">${hhmm(s.t)}</div></div>`;
  }).join("");
}

// -------------------------------------------------------- interaction ----
canvas.addEventListener("mousemove", (e) => {
  const L = state.layout; if (!L) return;
  const rect = canvas.getBoundingClientRect(); const px = e.clientX - rect.left, py = e.clientY - rect.top;
  const ci = Math.floor((px - L.plotL) / L.colW); const tip = $("tooltip");
  if (ci < 0 || ci >= L.n || px > L.plotR || py > L.plotB) { tip.classList.add("hidden"); if (state.hover !== -1) { state.hover = -1; markDirty(); } return; }
  state.hover = ci; const c = L.vis[ci];
  const buy = (c.v + (c.delta || 0)) / 2, sell = (c.v || 0) - buy;
  tip.innerHTML =
    `<div class="row"><span>${hhmm(c.t)}</span></div>` +
    `<div class="row"><span>O</span>${nf(c.o, 2)}</div><div class="row"><span>H</span>${nf(c.h, 2)}</div>` +
    `<div class="row"><span>L</span>${nf(c.l, 2)}</div><div class="row"><span>C</span>${nf(c.c, 2)}</div><hr/>` +
    `<div class="row"><span>Buy</span><b class="pos">${nf(buy, 2)}</b></div>` +
    `<div class="row"><span>Sell</span><b class="neg">${nf(sell, 2)}</b></div>` +
    `<div class="row"><span>Delta</span><b class="${(c.delta || 0) >= 0 ? "pos" : "neg"}">${sgn(c.delta || 0, 2)}</b></div>`;
  tip.classList.remove("hidden");
  const tw = tip.offsetWidth; tip.style.left = Math.min(px + 14, canvas.clientWidth - tw - 8) + "px"; tip.style.top = Math.max(py - 10, 8) + "px";
  markDirty();
});
canvas.addEventListener("mouseleave", () => { state.hover = -1; $("tooltip").classList.add("hidden"); markDirty(); });

// ------------------------------------------------------------- wiring ----
document.querySelectorAll("#mode-seg .sg").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#mode-seg .sg").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); state.mode = b.dataset.mode; loadSeed();
}));
document.querySelectorAll(".tg").forEach((b) => b.addEventListener("click", () => {
  const k = b.dataset.tg; state.toggles[k] = !state.toggles[k]; b.classList.toggle("on", state.toggles[k]); markDirty();
}));
["symbol", "interval", "candles"].forEach((id) => $(id).addEventListener("change", () => { closeWS(); stopPolling(); state.wsTries = 0; loadSeed(); }));
window.addEventListener("resize", resize);
setInterval(() => { renderSignals(); updateLive(); }, 2000);

// optional deep-link: ?mode=footprint&symbol=ETHUSDT&tf=5m&candles=40
(function initFromUrl() {
  const p = new URLSearchParams(location.search);
  const sym = p.get("symbol"); if (sym && [...$("symbol").options].some((o) => o.value === sym)) $("symbol").value = sym;
  const tf = p.get("tf"); if (tf && [...$("interval").options].some((o) => o.value === tf)) $("interval").value = tf;
  const cn = p.get("candles"); if (cn && [...$("candles").options].some((o) => o.value === cn)) $("candles").value = cn;
  if (p.get("mode") === "footprint") {
    state.mode = "footprint";
    document.querySelectorAll("#mode-seg .sg").forEach((x) => x.classList.toggle("on", x.dataset.mode === "footprint"));
  }
})();

loadSeed();
