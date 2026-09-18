/* OrderFlow Pro — professional order-flow terminal.
   Chart (footprint/candles/bars) + Delta/CVD/Volume panes, session volume
   profile, VWAP, liquidity heatmap, full L2 DOM, Time & Sales, alerts engine,
   drawing tools, crosshair, settings, persistence and keyboard shortcuts. */

import { CFG, newCandle, applyTrade, candleFromSeed, analyze } from "./footprint.js";
import { OrderBook } from "./orderbook.js";
import { Heatmap } from "./heatmap.js";
import { Alerts } from "./alerts.js";

const $ = (id) => document.getElementById(id);
const canvas = $("chart");
const ctx = canvas.getContext("2d");

const C = {
  bg: "#0a0d12", grid: "#12181f", gridWeak: "#0e141a", axisText: "#7a8797",
  up: "#26a269", down: "#d64541", upW: "#1c7a4f", downW: "#a5322f",
  buy: "#26a269", sell: "#d64541", buyT: "#5fd39c", sellT: "#f08a86",
  profUp: "#3a5fb0", profDn: "#8f3a3a",
  poc: "#e8a13c", vaLine: "#55627a", vaFill: "rgba(120,140,180,.045)",
  vwap: "#4a90d9", ice: "#37c3d6", absorb: "#b57ae0", paneBg: "#0b0f15", cross: "rgba(200,210,225,.28)",
};
const LS = "ofpro.v1";

const state = {
  symbol: "BTCUSDT", interval: "1m", basetick: 1, intervalMs: 60000,
  type: "footprint", fpmode: "bidask",
  panes: { delta: true, cvd: true, volume: true, profile: true, heatmap: false, dom: true, tape: true },
  settings: { imbRatio: 3.0, stackedMin: 3, clusterTicks: 1, bigTrade: 0.5, sound: true, notify: false },
  ohlc: [], candles: [], profile: [], va: { vpoc: 0, vah: 0, val: 0 },
  book: new OrderBook(), heat: new Heatmap(), alerts: new Alerts(), tape: [],
  ws: null, wsTries: 0, pollTimer: null, pruneTimer: null,
  metrics: { msgs: 0, ups: 0 },
  dirty: false, mouse: null, hover: -1, tab: "tape",
  tool: "cross", magnet: false, drawings: [], pending: null,
  heatLast: 0, layout: null,
};

// helpers
const nf = (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (n, d = 2) => (n >= 0 ? "+" : "") + nf(n, d);
const vf = (v) => v >= 1000 ? (v / 1000).toFixed(1) + "k" : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
const qf = (q) => q >= 100 ? q.toFixed(0) : q >= 1 ? q.toFixed(2) : q.toFixed(3);
const hhmm = (t) => { const d = new Date(t); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
const hms = (t) => { const d = new Date(t); return hhmm(t) + ":" + String(d.getSeconds()).padStart(2, "0"); };
const px2 = () => state.symbol.includes("BTC") ? 2 : state.symbol.includes("XRP") || state.symbol.includes("ADA") || state.symbol.includes("DOGE") ? 4 : 3;
function setConn(cls) { $("conn").className = "conn " + cls; }
function markDirty() { if (state.dirty) return; state.dirty = true; requestAnimationFrame(() => { state.dirty = false; draw(); }); }

// -------------------------------------------------------- persistence -----
function save() {
  try {
    localStorage.setItem(LS, JSON.stringify({
      symbol: state.symbol, interval: state.interval, type: state.type, fpmode: state.fpmode,
      panes: state.panes, settings: state.settings, drawings: state.drawings,
      candles: $("candles").value, tab: state.tab, alerts: state.alerts.toJSON(),
    }));
  } catch {}
}
function load() {
  let o; try { o = JSON.parse(localStorage.getItem(LS) || "null"); } catch { o = null; }
  if (!o) return;
  Object.assign(state, {
    symbol: o.symbol || state.symbol, interval: o.interval || state.interval,
    type: o.type || state.type, fpmode: o.fpmode || state.fpmode,
  });
  if (o.panes) Object.assign(state.panes, o.panes);
  if (o.settings) Object.assign(state.settings, o.settings);
  if (o.drawings) state.drawings = o.drawings;
  if (o.tab) state.tab = o.tab;
  if (o.alerts) state.alerts.load(o.alerts);
  // reflect into DOM
  [...$("symbol").options].forEach((op) => op.selected = op.value === state.symbol);
  document.querySelectorAll("#tf-seg button").forEach((b) => b.classList.toggle("on", b.dataset.tf === state.interval));
  document.querySelectorAll("#type-seg button").forEach((b) => b.classList.toggle("on", b.dataset.type === state.type));
  $("fpmode").value = state.fpmode; if (o.candles) $("candles").value = o.candles;
  document.querySelectorAll("#pane-chips .chip").forEach((b) => b.classList.toggle("on", !!state.panes[b.dataset.pane]));
  state.alerts.sound = state.settings.sound;
  syncSettingsUI();
}
function syncSettingsUI() {
  $("set-imb").value = Math.round(state.settings.imbRatio * 100);
  $("set-stk").value = state.settings.stackedMin; $("set-ticks").value = state.settings.clusterTicks;
  $("set-big").value = state.settings.bigTrade; $("set-sound").checked = state.settings.sound;
  $("set-notify").checked = state.settings.notify; $("set-heat").checked = state.panes.heatmap;
  $("tape-min").value = state.settings.bigTrade;
  $("dom-imb"); // noop
  $("heat-legend").classList.toggle("hidden", !state.panes.heatmap);
}

// ---------------------------------------------------------------- seed ----
async function loadSeed() {
  setConn("wait"); state.book.beginSync(); state.book.onResync = fetchDepth;
  try {
    const fp = Math.min(45, parseInt($("candles").value, 10));
    const [s, tr] = await Promise.all([
      fetch(`/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=140&fp=${fp}`).then((r) => r.json()),
      fetch(`/api/trades?symbol=${state.symbol}&limit=120`).then((r) => r.json()),
    ]);
    if (s.error) throw new Error(s.error);
    state.basetick = s.basetick; state.intervalMs = s.intervalMs;
    state.ohlc = s.candles; state.va = { vpoc: s.vpoc, vah: s.vah, val: s.val }; state.profile = s.profile;
    state.candles = s.footprints.map((f) => candleFromSeed(f, s.basetick));
    if (tr && tr.trades) state.tape = tr.trades.slice().reverse().map((t) => ({ p: t.p, q: t.q, m: t.m, T: t.T })).slice(0, 80);
    state.heat.cols.clear();
    connectWS(); fetchDepth();
    updateStatus(s.lastPrice); updateTape(); resize();
  } catch (e) { setConn("off"); $("st-conn").innerHTML = '<i class="dot"></i> ' + e.message; }
}
async function fetchDepth() {
  try { const d = await fetch(`/api/depth?symbol=${state.symbol}&limit=1000`).then((r) => r.json());
    if (!d.error) state.book.seedSnapshot(d); updateLadder(); markDirty(); } catch {}
}

// ------------------------------------------------------ live websocket ----
function wsUrls() {
  const s = state.symbol.toLowerCase();
  const st = `${s}@aggTrade/${s}@kline_${state.interval}/${s}@depth@100ms`;
  return [`wss://data-stream.binance.vision/stream?streams=${st}`, `wss://stream.binance.com:9443/stream?streams=${st}`];
}
function connectWS() {
  closeWS(); const url = wsUrls()[state.wsTries % 2]; let opened = false, ws;
  try { ws = new WebSocket(url); } catch { return startPolling(); }
  state.ws = ws;
  const ft = setTimeout(() => { if (!opened) try { ws.close(); } catch {} }, 4500);
  ws.onopen = () => { opened = true; state.wsTries = 0; clearTimeout(ft); stopPolling(); setConn("on");
    $("st-conn").innerHTML = '<i class="dot" style="background:var(--green)"></i> LIVE WS+L2';
    if (!state.pruneTimer) state.pruneTimer = setInterval(() => state.book.prune(), 5000); };
  ws.onmessage = (ev) => { state.metrics.msgs++; let m; try { m = JSON.parse(ev.data); } catch { return; } const d = m.data || m;
    if (d.e === "aggTrade") onTrade(d); else if (d.e === "kline") onKline(d.k);
    else if (d.e === "depthUpdate" || d.bids || d.asks) { state.book.applyDepth(d); markDirty(); } };
  ws.onclose = () => { clearTimeout(ft); if (!opened) state.wsTries++;
    if (state.wsTries >= 2 && !opened) { setConn("off"); $("st-conn").innerHTML = '<i class="dot" style="background:var(--red)"></i> REST fallback'; return startPolling(); }
    setConn("wait"); setTimeout(connectWS, 1200); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
function closeWS() { if (state.ws) { try { state.ws.onclose = null; state.ws.close(); } catch {} state.ws = null; } }

const bucketOf = (t) => Math.floor(t / state.intervalMs) * state.intervalMs;
function ensureFp(bt, p) { const l = state.candles[state.candles.length - 1]; if (l && l.t === bt) return l; if (l && bt > l.t) l.finished = true; const c = newCandle(bt, p); state.candles.push(c); if (state.candles.length > 60) state.candles.shift(); return c; }
function ensureOhlc(bt, p) { const l = state.ohlc[state.ohlc.length - 1]; if (l && l.t === bt) return l; const c = { t: bt, o: p, h: p, l: p, c: p, v: 0, delta: 0 }; state.ohlc.push(c); if (state.ohlc.length > 400) state.ohlc.shift(); return c; }

function onTrade(d) {
  const p = +d.p, q = +d.q, isSell = d.m;
  applyTrade(ensureFp(bucketOf(d.T), p), p, q, isSell, state.basetick);
  state.book.applyTrade(p, q, isSell);
  state.tape.unshift({ p, q, m: isSell, T: d.T }); if (state.tape.length > 100) state.tape.pop();
  updateStatus(p); updateTape(); markDirty();
}
function onKline(k) { const c = ensureOhlc(+k.t, +k.o); c.o = +k.o; c.h = +k.h; c.l = +k.l; c.c = +k.c; c.v = +k.v; c.delta = 2 * (+k.V) - (+k.v); updateStatus(+k.c); markDirty(); }

function startPolling() {
  if (state.pollTimer) return;
  const tick = async () => { try {
    const fp = Math.min(45, parseInt($("candles").value, 10));
    const [s, tr] = await Promise.all([
      fetch(`/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=140&fp=${fp}`).then((r) => r.json()),
      fetch(`/api/trades?symbol=${state.symbol}&limit=120`).then((r) => r.json()),
    ]);
    if (!s.error) { state.ohlc = s.candles; state.va = { vpoc: s.vpoc, vah: s.vah, val: s.val }; state.profile = s.profile; state.candles = s.footprints.map((f) => candleFromSeed(f, s.basetick)); updateStatus(s.lastPrice); }
    if (tr && tr.trades) state.tape = tr.trades.slice().reverse().map((t) => ({ p: t.p, q: t.q, m: t.m, T: t.T })).slice(0, 80);
    fetchDepth(); updateTape(); markDirty();
  } catch {} };
  state.pollTimer = setInterval(tick, 4000); tick();
}
function stopPolling() { if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; } }

// -------------------------------------------------------- footprint agg ---
function aggregate(candle, k) {
  if (k <= 1) return candle;
  const levels = new Map();
  for (const [idx, cell] of candle.levels) { const di = Math.floor(idx / k); let c = levels.get(di); if (!c) { c = { bid: 0, ask: 0 }; levels.set(di, c); } c.bid += cell.bid; c.ask += cell.ask; }
  return { ...candle, levels };
}
function sigCfg(c) { const v = [...c.levels.values()].map((x) => x.bid + x.ask); const m = v.reduce((a, b) => a + b, 0) / (v.length || 1); return { ...CFG, imbalanceRatio: state.settings.imbRatio, stackedMin: state.settings.stackedMin, imbalanceMinVol: m * 0.5 }; }

// ------------------------------------------------------------- status ------
function updateStatus(price) {
  $("st-sym").textContent = `${state.symbol} · ${state.interval}`;
  const b = state.book.best(), t = state.book.totals();
  const up = state.ohlc.length && price >= state.ohlc[state.ohlc.length - 1].o;
  $("st-last").innerHTML = `<span class="${up ? "pos" : "neg"}">${nf(price, px2())}</span>`;
  if (b.bid && b.ask) { $("st-spread").textContent = `spread ${nf(b.ask - b.bid, px2())}`; $("st-ba").innerHTML = `<span class="pos">${nf(b.bid, px2())}</span> / <span class="neg">${nf(b.ask, px2())}</span>`; }
  const cvd = state.ohlc.slice(-60).reduce((a, x) => a + x.delta, 0);
  $("st-cvd").innerHTML = `CVD <span class="${cvd >= 0 ? "pos" : "neg"}">${sgn(cvd, 0)}</span>`;
  $("st-book").textContent = `L2 ${t.levels} lvl` + (state.book.resyncs ? ` · ${state.book.resyncs} rsync` : "");
  const im = $("dom-imb");
  if (t.bid + t.ask > 0) { const v = t.imbalance; im.textContent = (v >= 0 ? "▲" : "▼") + nf(Math.abs(v) * 100, 0) + "%"; im.className = "dp-imb " + (v >= 0 ? "pos" : "neg"); }
  state.alerts.onPrice(price, (x) => nf(x, px2()));
}

// ---------------------------------------------------------- DOM ladder ----
function updateLadder() {
  if (!state.panes.dom) return; const el = $("ladder");
  const bids = [...state.book.bids.entries()].sort((a, b) => b[0] - a[0]);
  const asks = [...state.book.asks.entries()].sort((a, b) => b[0] - a[0]);
  if (!bids.length && !asks.length) { el.innerHTML = '<div class="empty">Esperando order book…</div>'; return; }
  const maxSz = Math.max(1e-9, ...bids.slice(0, 40).map((x) => x[1]), ...asks.slice(-40).map((x) => x[1]));
  const ice = state.book.flagged("iceberg"), abs = state.book.flagged("absorption"), d = px2();
  const row = (p, q, side) => { const w = Math.min(100, (q / maxSz) * 100);
    const fl = ice.has(p) ? '<span class="lad-flag">❄</span>' : abs.has(p) ? '<span class="lad-flag abs">◆</span>' : "";
    const bc = side === "bid" ? `<div class="sz b" style="background:linear-gradient(270deg,var(--bidfill) ${w}%,transparent ${w}%)">${vf(q)}${fl}</div>` : `<div class="sz"></div>`;
    const ac = side === "ask" ? `<div class="sz a" style="background:linear-gradient(90deg,var(--askfill) ${w}%,transparent ${w}%)">${fl}${vf(q)}</div>` : `<div class="sz"></div>`;
    return `<div class="lad-row ${side}">${bc}<div class="price">${nf(p, d)}</div>${ac}</div>`; };
  const b = state.book.best(), spread = b.bid && b.ask ? b.ask - b.bid : 0, t = state.book.totals();
  el.innerHTML = asks.slice(-12).map(([p, q]) => row(p, q, "ask")).join("") +
    `<div class="lad-row spread"><div class="sz b">Σ ${vf(t.bid)}</div><div class="price">↕ ${nf(spread, d)}</div><div class="sz a">Σ ${vf(t.ask)}</div></div>` +
    bids.slice(0, 12).map(([p, q]) => row(p, q, "bid")).join("");
}

// ---------------------------------------------------------- T&S tape ------
function updateTape() {
  if (!state.panes.tape || state.tab !== "tape") return; const el = $("tape");
  const min = state.settings.bigTrade, d = px2(), rows = state.tape.filter((t) => t.q >= 0.001).slice(0, 60);
  if (!rows.length) { el.innerHTML = '<div class="empty">Esperando trades…</div>'; return; }
  el.innerHTML = rows.map((t) => { const big = t.q >= min, whale = t.q >= min * 5; const cls = (t.m ? "sell" : "buy") + (big ? " big" : "") + (whale ? " whale" : "");
    return `<div class="tape-row ${cls}"><span class="tt">${hms(t.T)}</span><span class="tp">${nf(t.p, d)}</span><span class="tq">${qf(t.q)}</span></div>`; }).join("");
}

// ------------------------------------------------------------- alerts -----
function renderAlerts() {
  $("al-count").textContent = state.alerts.list.filter((a) => a.active).length;
  if (state.tab !== "alerts") return;
  const el = $("alerts-list"); const list = state.alerts.list;
  const icon = { price: "🔔", flow: "⚡" };
  const rows = list.map((a) => {
    const name = a.kind === "price" ? `Precio ${nf(a.price, px2())}` : `Flujo · ${a.flow}`;
    return `<div class="alert-item ${a.active ? "" : "off"}"><span class="ai">${icon[a.kind]}</span>
      <span class="aname">${name}<small>${a.hits} disparos${a.note ? " · " + a.note : ""}</small></span>
      <button class="ax" data-tg="${a.id}">${a.active ? "⏸" : "▶"}</button>
      <button class="ax" data-rm="${a.id}">✕</button></div>`; }).join("");
  const logRows = state.alerts.log.slice(0, 6).map((l) => `<div class="alert-item"><span class="ai">•</span><span class="aname">${l.text}<small>${hms(l.t)}</small></span><span></span><span></span></div>`).join("");
  el.innerHTML = (rows || '<div class="empty">Sin alertas.</div>') + (logRows ? '<div class="empty" style="text-align:left;padding:6px 4px 2px">HISTORIAL</div>' + logRows : "");
  el.querySelectorAll("[data-tg]").forEach((b) => b.onclick = () => { state.alerts.toggle(+b.dataset.tg); save(); });
  el.querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => { state.alerts.remove(+b.dataset.rm); save(); });
}
function toast(text, kind) {
  const host = $("toasts"); const el = document.createElement("div"); el.className = "toast " + (kind || "");
  el.textContent = text; host.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, 5200);
}
let lastFlowT = 0;
function checkFlow() {
  const s = state.book.signals;
  for (const sig of s) { if (sig.t <= lastFlowT) break; state.alerts.onFlow(sig.type, sig.detail); }
  if (s.length) lastFlowT = Math.max(lastFlowT, s[0].t);
  // stacked from last finished footprint candle
  const c = state.candles[state.candles.length - 2];
  if (c) { const a = analyze(aggregate(c, 1), sigCfg(aggregate(c, 1))); for (const st of a.stacks) if (c.t > (state._lastStkT || 0)) { state.alerts.onFlow("stacked", `${st.dir} ×${st.count}`); state._lastStkT = c.t; } }
}

// ------------------------------------------------------------ geometry ----
const AX_W = 66, TIME_H = 20, TOP = 6;
function paneList() { return ["delta", "cvd", "volume"].filter((k) => state.panes[k]); }
function resize() { const dpr = window.devicePixelRatio || 1; const w = canvas.clientWidth, h = canvas.clientHeight; canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw(); }
function computeLayout() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const isFp = state.type === "footprint"; const src = isFp ? state.candles : state.ohlc;
  const n = Math.min(src.length, parseInt($("candles").value, 10)); const vis = src.slice(src.length - n); if (!vis.length) return null;
  const profW = state.panes.profile ? (isFp ? 60 : 128) : 4;
  const plotL = profW, plotR = w - AX_W;
  const panes = paneList(), paneH = 74, panesTotal = panes.length * paneH;
  const mainTop = TOP, mainBot = h - TIME_H - panesTotal;
  let lo = Infinity, hi = -Infinity; for (const c of vis) { if (c.l < lo) lo = c.l; if (c.h > hi) hi = c.h; }
  if (!isFp) { lo = Math.min(lo, state.va.val); hi = Math.max(hi, state.va.vah); }
  const pad = (hi - lo) * 0.04; lo -= pad; hi += pad; if (!(hi > lo)) hi = lo + state.basetick * 10;
  const y = (p) => mainBot - ((p - lo) / (hi - lo)) * (mainBot - mainTop);
  const colW = (plotR - plotL) / n, colX = (i) => plotL + i * colW + colW / 2;
  const L = { w, h, isFp, vis, n, lo, hi, plotL, plotR, profW, mainTop, mainBot, y, colW, colX, paneH, panes };
  if (isFp) { const availH = mainBot - mainTop; const rows = Math.min(80, Math.max(8, Math.floor(availH / 13)));
    const k = Math.max(1, Math.ceil(((hi - lo) / state.basetick) / rows)) * state.settings.clusterTicks;
    L.k = k; L.dTick = state.basetick * k; L.rowLo = Math.floor(lo / L.dTick); L.rowHi = Math.ceil(hi / L.dTick);
    L.rowH = availH / Math.max(1, L.rowHi - L.rowLo); L.rowY = (di) => mainBot - (di - L.rowLo) * L.rowH; }
  return L;
}

// ---------------------------------------------------------------- draw ----
function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight; ctx.clearRect(0, 0, w, h); ctx.fillStyle = C.bg; ctx.fillRect(0, 0, w, h);
  const L = computeLayout(); state.layout = L; if (!L) return;
  drawGridV(L); drawValueArea(L);
  if (state.panes.heatmap) drawHeatmap(L);
  if (state.panes.profile) drawProfile(L);
  if (L.isFp) drawClusters(L); else drawCandles(L);
  if (!L.isFp) drawVWAP(L);
  drawLevels(L); drawAlertLines(L); drawPanes(L);
  drawPriceAxis(L); drawTimeAxis(L); drawLastPrice(L); drawDrawings(L); drawCrosshair(L); updateLegend(L);
}
function drawGridV(L) { ctx.strokeStyle = C.gridWeak; ctx.lineWidth = 1; const step = Math.max(1, Math.floor(L.n / 12));
  for (let i = 0; i <= L.n; i += step) { const x = Math.round(L.plotL + i * L.colW) + .5; ctx.beginPath(); ctx.moveTo(x, L.mainTop); ctx.lineTo(x, L.mainBot); ctx.stroke(); } }
function drawValueArea(L) { const yH = L.y(state.va.vah), yL = L.y(state.va.val); ctx.fillStyle = C.vaFill; ctx.fillRect(L.plotL, Math.min(yH, yL), L.plotR - L.plotL, Math.abs(yL - yH)); }

function drawHeatmap(L) {
  const now = Date.now();
  const rowsWanted = Math.max(24, Math.floor((L.mainBot - L.mainTop) / 3));
  const tick = state.basetick * Math.max(1, Math.ceil(((L.hi - L.lo) / state.basetick) / rowsWanted));
  if (now - state.heatLast > 400) { state.heat.capture(L.vis[L.vis.length - 1].t, state.book, tick, L.lo, L.hi); state.heatLast = now; state.heat.prune(L.vis.map((c) => c.t)); }
  const liveCol = state.heat.live(state.book, tick, L.lo, L.hi);
  const mx = Math.max(state.heat.max, 1e-9);
  L.vis.forEach((c, ci) => {
    const col = state.heat.column(c.t) || liveCol; const t2 = col.tick, x0 = L.plotL + ci * L.colW;
    const rowH = Math.max(1, (t2 / (L.hi - L.lo)) * (L.mainBot - L.mainTop));
    for (const [b, size] of col.map) { const price = b * t2; if (price < L.lo || price > L.hi) continue;
      const inten = Math.min(1, Math.log(1 + size) / Math.log(1 + mx));
      if (inten < 0.12) continue;
      ctx.fillStyle = Heatmap.color(inten); ctx.globalAlpha = 0.05 + 0.32 * inten;
      ctx.fillRect(x0, L.y(price) - rowH / 2, L.colW + 0.5, rowH); }
  });
  ctx.globalAlpha = 1;
}

function drawProfile(L) {
  if (L.isFp) return drawFpProfile(L);
  if (!state.profile.length) return;
  const inR = state.profile.filter((p) => p.price >= L.lo && p.price <= L.hi);
  const maxV = Math.max(1, ...inR.map((p) => p.vol)); const bh = Math.max(1, (L.mainBot - L.mainTop) / (inR.length || 1) - .5);
  for (const p of state.profile) { if (p.price < L.lo || p.price > L.hi) continue; const yy = L.y(p.price); const wgt = (p.vol / maxV) * (L.profW - 8);
    ctx.fillStyle = p.price >= state.va.vpoc ? C.profUp : C.profDn; ctx.globalAlpha = .5; ctx.fillRect(L.profW - wgt, yy - bh / 2, wgt, bh); ctx.globalAlpha = 1; }
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.profW + .5, L.mainTop); ctx.lineTo(L.profW + .5, L.mainBot); ctx.stroke();
}
function drawFpProfile(L) {
  const prof = new Map(); let maxV = 0;
  for (const base of L.vis) { const c = aggregate(base, L.k); for (const [di, cell] of c.levels) { let p = prof.get(di); if (!p) { p = { bid: 0, ask: 0 }; prof.set(di, p); } p.bid += cell.bid; p.ask += cell.ask; maxV = Math.max(maxV, p.bid + p.ask); } }
  maxV = maxV || 1;
  for (const [di, cell] of prof) { const yTop = L.rowY(di + 1), hgt = Math.max(1, L.rowH - .5); const bw = (cell.ask / maxV) * (L.profW - 5), sw = (cell.bid / maxV) * (L.profW - 5);
    ctx.globalAlpha = .55; ctx.fillStyle = C.buy; ctx.fillRect(L.profW - bw, yTop, bw, hgt); ctx.fillStyle = C.sell; ctx.fillRect(L.profW - bw - sw, yTop, sw, hgt); ctx.globalAlpha = 1; }
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.profW + .5, L.mainTop); ctx.lineTo(L.profW + .5, L.mainBot); ctx.stroke();
}
function drawCandles(L) {
  const bars = state.type === "bars"; const bw = Math.max(1.5, Math.min(bars ? 6 : 10, L.colW * (bars ? 0.5 : 0.62)));
  L.vis.forEach((c, i) => { const x = L.colX(i), up = c.c >= c.o;
    if (bars) { ctx.strokeStyle = up ? C.up : C.down; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.moveTo(x, L.y(c.h)); ctx.lineTo(x, L.y(c.l)); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - bw, L.y(c.o)); ctx.lineTo(x, L.y(c.o)); ctx.moveTo(x, L.y(c.c)); ctx.lineTo(x + bw, L.y(c.c)); ctx.stroke(); }
    else { ctx.strokeStyle = up ? C.upW : C.downW; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, L.y(c.h)); ctx.lineTo(x, L.y(c.l)); ctx.stroke();
      ctx.fillStyle = up ? C.up : C.down; const top = Math.min(L.y(c.o), L.y(c.c)), hg = Math.max(1, Math.abs(L.y(c.c) - L.y(c.o))); ctx.fillRect(x - bw / 2, top, bw, hg); }
    if (i === state.hover) { ctx.strokeStyle = "rgba(255,255,255,.4)"; ctx.lineWidth = 1; ctx.strokeRect(x - bw / 2 - 1, L.y(c.h) - 1, bw + 2, L.y(c.l) - L.y(c.h) + 2); }
  });
}
function drawVWAP(L) { let pv = 0, vv = 0; const pts = []; for (const c of L.vis) { const tp = (c.h + c.l + c.c) / 3; pv += tp * c.v; vv += c.v; pts.push(vv ? pv / vv : c.c); }
  ctx.strokeStyle = C.vwap; ctx.lineWidth = 1.4; ctx.beginPath(); pts.forEach((v, i) => { const x = L.colX(i); i ? ctx.lineTo(x, L.y(v)) : ctx.moveTo(x, L.y(v)); }); ctx.stroke(); }

function drawClusters(L) {
  const showNums = L.colW >= 40 && L.rowH >= 9.5; ctx.textBaseline = "middle"; ctx.font = `${Math.max(7.5, Math.min(10, L.rowH - 2))}px ui-monospace, Menlo, monospace`;
  L.vis.forEach((base, ci) => {
    const c = aggregate(base, L.k), a = analyze(c, sigCfg(c)); const x0 = L.plotL + ci * L.colW, midX = x0 + L.colW / 2;
    let cmax = 1, dmax = 1; for (const cell of c.levels.values()) { cmax = Math.max(cmax, cell.bid + cell.ask); dmax = Math.max(dmax, Math.abs(cell.ask - cell.bid)); }
    const up = c.c >= c.o; ctx.globalAlpha = .4; ctx.strokeStyle = up ? C.up : C.down; ctx.beginPath(); ctx.moveTo(midX, L.y(c.h)); ctx.lineTo(midX, L.y(c.l)); ctx.stroke(); ctx.globalAlpha = 1;
    for (const [di, cell] of c.levels) { const yTop = L.rowY(di + 1), yMid = yTop + L.rowH / 2; if (yTop > L.mainBot || yTop + L.rowH < L.mainTop) continue;
      const vol = cell.bid + cell.ask, dl = cell.ask - cell.bid, half = (L.colW - 2) / 2;
      if (state.fpmode === "delta") { ctx.fillStyle = dl >= 0 ? C.buy : C.sell; ctx.globalAlpha = .12 + .3 * (Math.abs(dl) / dmax); ctx.fillRect(x0 + 1, yTop + .5, L.colW - 2, L.rowH - 1); ctx.globalAlpha = 1;
        if (showNums) { ctx.textAlign = "center"; ctx.fillStyle = dl >= 0 ? C.buyT : C.sellT; ctx.fillText(sgn(dl, dl > 9 || dl < -9 ? 0 : 1).replace("+", ""), midX, yMid); } }
      else if (state.fpmode === "volume") { ctx.fillStyle = "#4a6a9a"; ctx.globalAlpha = .12 + .32 * (vol / cmax); ctx.fillRect(x0 + 1, yTop + .5, L.colW - 2, L.rowH - 1); ctx.globalAlpha = 1;
        if (showNums) { ctx.textAlign = "center"; ctx.fillStyle = "#aebfd2"; ctx.fillText(vf(vol), midX, yMid); } }
      else { ctx.fillStyle = C.sell; ctx.globalAlpha = .1 + .3 * (cell.bid / cmax); ctx.fillRect(x0 + 1, yTop + .5, half, L.rowH - 1);
        ctx.fillStyle = C.buy; ctx.globalAlpha = .1 + .3 * (cell.ask / cmax); ctx.fillRect(midX, yTop + .5, half, L.rowH - 1); ctx.globalAlpha = 1;
        if (showNums) { ctx.textAlign = "right"; ctx.fillStyle = cell.bid > 0 ? C.sellT : "#3a4450"; ctx.fillText(vf(cell.bid), midX - 3, yMid); ctx.textAlign = "left"; ctx.fillStyle = cell.ask > 0 ? C.buyT : "#3a4450"; ctx.fillText(vf(cell.ask), midX + 3, yMid); } }
      const dir = a.flags.get(di);
      if (dir === "buy" && state.fpmode !== "volume") { ctx.strokeStyle = C.buy; ctx.lineWidth = 1.3; ctx.strokeRect(midX + .5, yTop + 1, half - 1, L.rowH - 2); }
      else if (dir === "sell" && state.fpmode !== "volume") { ctx.strokeStyle = C.sell; ctx.lineWidth = 1.3; ctx.strokeRect(x0 + 1.5, yTop + 1, half - 1, L.rowH - 2); }
    }
    for (const st of a.stacks) { const yA = L.rowY(st.to + 1), yB = L.rowY(st.from); ctx.strokeStyle = st.dir === "buy" ? C.buy : C.sell; ctx.lineWidth = 2.5; const bx = st.dir === "buy" ? x0 + L.colW - 2 : x0 + 2; ctx.beginPath(); ctx.moveTo(bx, yA); ctx.lineTo(bx, yB); ctx.stroke(); }
    if (a.poc != null) { const yTop = L.rowY(a.poc + 1); ctx.strokeStyle = C.poc; ctx.lineWidth = 1; ctx.strokeRect(x0 + 1, yTop + .5, L.colW - 2, L.rowH - 1); }
    if (ci === state.hover) { ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = 1; ctx.strokeRect(x0 + .5, L.mainTop, L.colW, L.mainBot - L.mainTop); }
  });
  ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
}
function levelLine(L, price, color, label, dash) { const yy = Math.round(L.y(price)) + .5; if (yy < L.mainTop || yy > L.mainBot) return;
  ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(dash ? [5, 4] : []); ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = color; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "left"; ctx.fillText(label, L.plotL + 3, yy - 3); }
function drawLevels(L) { levelLine(L, state.va.vah, C.vaLine, "VAH", true); levelLine(L, state.va.val, C.vaLine, "VAL", true); levelLine(L, state.va.vpoc, C.poc, "POC", false); }
function drawAlertLines(L) { for (const a of state.alerts.list) { if (a.kind !== "price" || !a.active) continue; const yy = Math.round(L.y(a.price)) + .5; if (yy < L.mainTop || yy > L.mainBot) continue;
  ctx.strokeStyle = C.poc; ctx.lineWidth = 1; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = C.poc; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "right"; ctx.fillText("🔔 " + nf(a.price, px2()), L.plotR - 4, yy - 3); } }

function drawPanes(L) { let top = L.mainBot; for (const key of L.panes) { const bot = top + L.paneH; drawPane(L, key, top, bot); top = bot; } }
function drawPane(L, key, top, bot) {
  ctx.fillStyle = C.paneBg; ctx.fillRect(L.plotL, top, L.plotR - L.plotL, bot - top);
  ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.plotL, top + .5); ctx.lineTo(L.plotR, top + .5); ctx.stroke();
  ctx.fillStyle = C.axisText; ctx.font = "9px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.fillText({ delta: "DELTA", cvd: "CVD", volume: "VOLUME" }[key], L.plotL + 4, top + 11);
  const vis = state.type === "footprint" ? state.candles.slice(state.candles.length - L.n) : L.vis;
  if (key === "cvd") { let cum = 0; const pts = vis.map((c) => (cum += c.delta || 0)); let mn = Math.min(0, ...pts), mx = Math.max(0, ...pts); if (mx === mn) { mx += 1; mn -= 1; }
    const yy = (v) => bot - 6 - ((v - mn) / (mx - mn)) * (bot - top - 12);
    ctx.strokeStyle = C.grid; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(L.plotL, yy(0)); ctx.lineTo(L.plotR, yy(0)); ctx.stroke(); ctx.setLineDash([]);
    ctx.lineWidth = 1.5; ctx.beginPath(); pts.forEach((v, i) => { const x = L.colX(i); i ? ctx.lineTo(x, yy(v)) : ctx.moveTo(x, yy(v)); }); ctx.strokeStyle = pts[pts.length - 1] >= 0 ? C.up : C.down; ctx.stroke();
    ctx.fillStyle = pts[pts.length - 1] >= 0 ? C.buyT : C.sellT; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "right"; ctx.fillText(sgn(pts[pts.length - 1], 0), L.plotR - 4, top + 11); }
  else if (key === "delta") { let ma = 1; for (const c of vis) ma = Math.max(ma, Math.abs(c.delta || 0)); const mid = (top + bot) / 2;
    vis.forEach((c, i) => { const x0 = L.plotL + i * L.colW; const bh = (Math.abs(c.delta || 0) / ma) * ((bot - top) / 2 - 6); ctx.fillStyle = (c.delta || 0) >= 0 ? C.buy : C.sell; if ((c.delta || 0) >= 0) ctx.fillRect(x0 + 1.5, mid - bh, L.colW - 3, bh); else ctx.fillRect(x0 + 1.5, mid, L.colW - 3, bh); });
    ctx.strokeStyle = C.grid; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(L.plotL, mid + .5); ctx.lineTo(L.plotR, mid + .5); ctx.stroke(); ctx.setLineDash([]); }
  else if (key === "volume") { let ma = 1; for (const c of vis) ma = Math.max(ma, c.v || (c.buy + c.sell) || 0);
    vis.forEach((c, i) => { const x0 = L.plotL + i * L.colW; const vol = c.v || (c.buy + c.sell) || 0; const bh = (vol / ma) * (bot - top - 14); const up = c.c >= c.o; ctx.fillStyle = up ? C.up : C.down; ctx.globalAlpha = .8; ctx.fillRect(x0 + 1.5, bot - bh - 2, L.colW - 3, bh); ctx.globalAlpha = 1; }); }
  L[`pane_${key}`] = { top, bot };
}
function drawPriceAxis(L) { ctx.fillStyle = C.axisText; ctx.font = "10px ui-monospace, Menlo, monospace"; ctx.textAlign = "left"; const steps = 9;
  for (let i = 0; i <= steps; i++) { const p = L.lo + (i / steps) * (L.hi - L.lo), yy = Math.round(L.y(p)); if (yy < L.mainTop || yy > L.mainBot) continue;
    ctx.strokeStyle = C.gridWeak; ctx.beginPath(); ctx.moveTo(L.plotL, yy + .5); ctx.lineTo(L.plotR, yy + .5); ctx.stroke(); ctx.fillStyle = C.axisText; ctx.fillText(nf(p, p > 1000 ? 1 : px2()), L.plotR + 5, yy + 3); } }
function drawTimeAxis(L) { ctx.fillStyle = C.axisText; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "center"; const y = L.h - 6, step = Math.ceil(L.n / 10);
  L.vis.forEach((c, ci) => { if (ci % step) return; ctx.fillText(hhmm(c.t), L.colX(ci), y); }); }
function drawLastPrice(L) { const src = L.isFp ? state.candles : state.ohlc; const last = src[src.length - 1]; if (!last) return;
  const yy = Math.round(L.y(last.c)) + .5; if (yy < L.mainTop || yy > L.mainBot) return; const up = last.c >= last.o;
  ctx.strokeStyle = up ? C.up : C.down; ctx.setLineDash([2, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = up ? C.up : C.down; ctx.fillRect(L.plotR, yy - 8, AX_W, 16); ctx.fillStyle = "#08090c"; ctx.font = "bold 10px ui-monospace, Menlo, monospace"; ctx.textAlign = "left"; ctx.fillText(nf(last.c, px2()), L.plotR + 4, yy + 3); }

// drawings + crosshair
function priceAt(y, L) { return L.lo + (L.mainBot - y) / (L.mainBot - L.mainTop) * (L.hi - L.lo); }
function timeAt(x, L) { const i = Math.round((x - L.plotL) / L.colW - .5); const c = L.vis[Math.max(0, Math.min(L.vis.length - 1, i))]; return c ? c.t : 0; }
function xForTime(t, L) { let best = 0, bd = Infinity; L.vis.forEach((c, i) => { const d = Math.abs(c.t - t); if (d < bd) { bd = d; best = i; } }); return L.colX(best); }
function drawDrawings(L) {
  for (const d of state.drawings) {
    if (d.type === "hline") { const yy = Math.round(L.y(d.price)) + .5; if (yy < L.mainTop || yy > L.mainBot) continue;
      ctx.strokeStyle = "#7f8aa0"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke();
      ctx.fillStyle = "#9aa6b8"; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "right"; ctx.fillText(nf(d.price, px2()), L.plotR - 4, yy - 3); }
    else if (d.type === "trend" && d.p2) { const x1 = xForTime(d.p1.t, L), y1 = L.y(d.p1.price), x2 = xForTime(d.p2.t, L), y2 = L.y(d.p2.price);
      ctx.strokeStyle = "#c9a94a"; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
    else if (d.type === "ruler" && d.p2) { const x1 = xForTime(d.p1.t, L), y1 = L.y(d.p1.price), x2 = xForTime(d.p2.t, L), y2 = L.y(d.p2.price);
      ctx.fillStyle = d.p2.price >= d.p1.price ? "rgba(38,162,105,.12)" : "rgba(214,69,65,.12)"; ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      ctx.strokeStyle = "#8b97a6"; ctx.setLineDash([3, 3]); ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); ctx.setLineDash([]);
      const dp = d.p2.price - d.p1.price, pct = dp / d.p1.price * 100, bars = Math.round(Math.abs(d.p2.t - d.p1.t) / state.intervalMs);
      ctx.fillStyle = "#e6ebf1"; ctx.font = "10px ui-monospace, Menlo, monospace"; ctx.textAlign = "center"; ctx.fillText(`${sgn(dp, px2())} (${sgn(pct, 2)}%) · ${bars} velas`, (x1 + x2) / 2, Math.min(y1, y2) - 5); }
  }
}
function drawCrosshair(L) { if (!state.mouse) return; const { x, y } = state.mouse; if (x < L.plotL || x > L.plotR) return;
  const paneBot = L.panes.length ? L[`pane_${L.panes[L.panes.length - 1]}`].bot : L.mainBot;
  ctx.strokeStyle = C.cross; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(Math.round(x) + .5, L.mainTop); ctx.lineTo(Math.round(x) + .5, paneBot); ctx.stroke();
  if (y >= L.mainTop && y <= L.mainBot) { ctx.beginPath(); ctx.moveTo(L.plotL, Math.round(y) + .5); ctx.lineTo(L.plotR, Math.round(y) + .5); ctx.stroke(); } ctx.setLineDash([]);
  if (y >= L.mainTop && y <= L.mainBot) { const p = priceAt(y, L); ctx.fillStyle = "#2a3341"; ctx.fillRect(L.plotR, y - 8, AX_W, 16); ctx.fillStyle = "#e6ebf1"; ctx.font = "10px ui-monospace, Menlo, monospace"; ctx.textAlign = "left"; ctx.fillText(nf(p, px2()), L.plotR + 4, y + 3); }
  const t = timeAt(x, L); ctx.fillStyle = "#2a3341"; ctx.fillRect(x - 26, L.h - TIME_H + 1, 52, TIME_H - 2); ctx.fillStyle = "#e6ebf1"; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "center"; ctx.fillText(hhmm(t), x, L.h - 6); }
function updateLegend(L) { const i = state.hover >= 0 ? state.hover : L.vis.length - 1; const c = L.vis[i]; if (!c) return;
  $("legend").innerHTML = `<span>${state.symbol} · ${state.interval} · ${state.type}</span><span>O<b>${nf(c.o, px2())}</b> H<b>${nf(c.h, px2())}</b> L<b>${nf(c.l, px2())}</b> C<b>${nf(c.c, px2())}</b></span><span>Vol<b>${vf(c.v || (c.buy + c.sell) || 0)}</b></span><span>Δ<b class="${(c.delta || 0) >= 0 ? "pos" : "neg"}">${sgn(c.delta || 0, 1)}</b></span>`; }

// -------------------------------------------------------- interaction ----
canvas.addEventListener("mousemove", (e) => { const L = state.layout; if (!L) return; const r = canvas.getBoundingClientRect(); const x = e.clientX - r.left, y = e.clientY - r.top; state.mouse = { x, y };
  const ci = Math.floor((x - L.plotL) / L.colW); state.hover = (ci >= 0 && ci < L.n && x <= L.plotR) ? ci : -1; const tip = $("tooltip");
  if (state.hover < 0 || y > L.mainBot) tip.classList.add("hidden");
  else { const c = L.vis[state.hover]; const vol = c.v || (c.buy + c.sell) || 0, buy = (vol + (c.delta || 0)) / 2, sell = vol - buy;
    tip.innerHTML = `<div class="r"><span>${hhmm(c.t)}</span></div><div class="r"><span>O</span>${nf(c.o, px2())}</div><div class="r"><span>H</span>${nf(c.h, px2())}</div><div class="r"><span>L</span>${nf(c.l, px2())}</div><div class="r"><span>C</span>${nf(c.c, px2())}</div><hr/><div class="r"><span>Buy</span><b class="pos">${nf(buy, 2)}</b></div><div class="r"><span>Sell</span><b class="neg">${nf(sell, 2)}</b></div><div class="r"><span>Δ</span><b class="${(c.delta || 0) >= 0 ? "pos" : "neg"}">${sgn(c.delta || 0, 2)}</b></div>`;
    tip.classList.remove("hidden"); const tw = tip.offsetWidth; tip.style.left = Math.min(x + 16, canvas.clientWidth - tw - 8) + "px"; tip.style.top = Math.max(y - 8, 6) + "px"; }
  markDirty();
});
canvas.addEventListener("mouseleave", () => { state.mouse = null; state.hover = -1; $("tooltip").classList.add("hidden"); markDirty(); });
canvas.addEventListener("click", (e) => { const L = state.layout; if (!L) return; const r = canvas.getBoundingClientRect(); const x = e.clientX - r.left, y = e.clientY - r.top;
  if (x < L.plotL || x > L.plotR || y < L.mainTop || y > L.mainBot) return;
  let price = priceAt(y, L); if (state.magnet) { const c = L.vis[Math.max(0, Math.min(L.vis.length - 1, Math.floor((x - L.plotL) / L.colW)))]; if (c) price = [c.o, c.h, c.l, c.c].reduce((a, b) => Math.abs(b - price) < Math.abs(a - price) ? b : a); }
  const t = timeAt(x, L);
  if (state.tool === "hline") { state.drawings.push({ type: "hline", price }); save(); }
  else if (state.tool === "alert") { state.alerts.addPrice(price); renderAlerts(); save(); toast(`Alerta creada en ${nf(price, px2())}`, "up"); }
  else if (state.tool === "trend" || state.tool === "ruler") { if (!state.pending) state.pending = { type: state.tool, p1: { price, t } }; else { state.drawings.push({ type: state.pending.type, p1: state.pending.p1, p2: { price, t } }); state.pending = null; save(); } }
  markDirty();
});

// left rail
document.querySelectorAll(".rl").forEach((b) => b.addEventListener("click", () => { const tool = b.dataset.tool;
  if (tool === "clear") { state.drawings = []; state.pending = null; save(); markDirty(); return; }
  if (tool === "magnet") { state.magnet = !state.magnet; b.classList.toggle("on", state.magnet); return; }
  document.querySelectorAll(".rl[data-tool]").forEach((x) => { if (!["clear", "magnet"].includes(x.dataset.tool)) x.classList.remove("on"); }); b.classList.add("on"); state.tool = tool; state.pending = null; }));

// toolbar
$("symbol").addEventListener("change", () => { state.symbol = $("symbol").value; reload(); });
document.querySelectorAll("#tf-seg button").forEach((b) => b.addEventListener("click", () => { document.querySelectorAll("#tf-seg button").forEach((x) => x.classList.remove("on")); b.classList.add("on"); state.interval = b.dataset.tf; reload(); }));
document.querySelectorAll("#type-seg button").forEach((b) => b.addEventListener("click", () => { document.querySelectorAll("#type-seg button").forEach((x) => x.classList.remove("on")); b.classList.add("on"); state.type = b.dataset.type; save(); markDirty(); }));
$("fpmode").addEventListener("change", () => { state.fpmode = $("fpmode").value; save(); markDirty(); });
$("candles").addEventListener("change", () => { save(); markDirty(); });
document.querySelectorAll("#pane-chips .chip").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.pane; state.panes[k] = !state.panes[k]; b.classList.toggle("on", state.panes[k]);
  document.querySelector(".dock-panel.dom").style.display = state.panes.dom ? "" : "none";
  document.querySelector(".dock-panel.botpanel").style.display = (state.panes.tape || state.panes.alerts) ? "" : "none";
  $("heat-legend").classList.toggle("hidden", !state.panes.heatmap);
  if (state.panes.dom) updateLadder(); if (state.panes.tape) updateTape(); save(); markDirty(); }));
$("tape-min").addEventListener("change", () => { state.settings.bigTrade = parseFloat($("tape-min").value) || 0; syncSettingsUI(); updateTape(); save(); });

// dock tabs
document.querySelectorAll(".dp-tab").forEach((b) => b.addEventListener("click", () => { document.querySelectorAll(".dp-tab").forEach((x) => x.classList.remove("on")); b.classList.add("on"); state.tab = b.dataset.tab;
  $("tab-tape").classList.toggle("hidden", state.tab !== "tape"); $("tab-alerts").classList.toggle("hidden", state.tab !== "alerts");
  $("tape-flt").style.display = state.tab === "tape" ? "" : "none"; if (state.tab === "tape") updateTape(); else renderAlerts(); save(); }));

// alerts panel buttons
$("al-add").onclick = () => { const last = state.ohlc[state.ohlc.length - 1]; if (last) { state.alerts.addPrice(last.c); renderAlerts(); save(); toast(`Alerta en ${nf(last.c, px2())}`, "up"); } };
$("al-ice").onclick = () => { state.alerts.addFlow("iceberg"); renderAlerts(); save(); };
$("al-abs").onclick = () => { state.alerts.addFlow("absorption"); renderAlerts(); save(); };
$("al-stk").onclick = () => { state.alerts.addFlow("stacked"); renderAlerts(); save(); };

// settings modal
function openModal() { syncSettingsUI(); $("modal").classList.remove("hidden"); }
function closeModal() { $("modal").classList.add("hidden"); }
$("btn-settings").onclick = openModal; $("modal-close").onclick = closeModal; $("modal-ok").onclick = closeModal;
$("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
function applySettings() {
  state.settings.imbRatio = Math.max(1, (parseFloat($("set-imb").value) || 300) / 100);
  state.settings.stackedMin = Math.max(2, parseInt($("set-stk").value, 10) || 3);
  state.settings.clusterTicks = Math.max(1, parseInt($("set-ticks").value, 10) || 1);
  state.settings.bigTrade = parseFloat($("set-big").value) || 0; $("tape-min").value = state.settings.bigTrade;
  state.settings.sound = $("set-sound").checked; state.alerts.sound = state.settings.sound;
  state.settings.notify = $("set-notify").checked; if (state.settings.notify) state.alerts.requestNotify();
  const heat = $("set-heat").checked; state.panes.heatmap = heat; document.querySelector('#pane-chips [data-pane="heatmap"]').classList.toggle("on", heat); $("heat-legend").classList.toggle("hidden", !heat);
  save(); markDirty();
}
["set-imb", "set-stk", "set-ticks", "set-big", "set-sound", "set-notify", "set-heat"].forEach((id) => $(id).addEventListener("change", applySettings));
$("set-reset").onclick = () => { state.settings = { imbRatio: 3.0, stackedMin: 3, clusterTicks: 1, bigTrade: 0.5, sound: true, notify: false }; syncSettingsUI(); save(); markDirty(); };

// keyboard shortcuts
window.addEventListener("keydown", (e) => { if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return; const k = e.key.toLowerCase();
  const setType = (t) => { state.type = t; document.querySelectorAll("#type-seg button").forEach((x) => x.classList.toggle("on", x.dataset.type === t)); save(); markDirty(); };
  if (k === "f") setType("footprint"); else if (k === "c") setType("candles"); else if (k === "b") setType("bars");
  else if (k === "h") { state.panes.heatmap = !state.panes.heatmap; document.querySelector('#pane-chips [data-pane="heatmap"]').classList.toggle("on", state.panes.heatmap); $("heat-legend").classList.toggle("hidden", !state.panes.heatmap); save(); markDirty(); }
  else if (k === "s") openModal(); else if (k === "escape") closeModal();
  else if (k === "v") document.querySelector('.rl[data-tool="cross"]').click();
  else if (k === "a") document.querySelector('.rl[data-tool="alert"]').click();
  else if (k === "+" || k === "=") { const o = $("candles"); if (o.selectedIndex < o.options.length - 1) { o.selectedIndex++; save(); markDirty(); } }
  else if (k === "-") { const o = $("candles"); if (o.selectedIndex > 0) { o.selectedIndex--; save(); markDirty(); } }
});

function reload() { closeWS(); stopPolling(); state.wsTries = 0; loadSeed(); save(); }
window.addEventListener("resize", resize);

// periodic housekeeping
setInterval(() => { $("tb-clock").textContent = hms(Date.now()); if (state.panes.dom) updateLadder(); state.metrics.ups = state.metrics.msgs; state.metrics.msgs = 0; $("st-ups").textContent = `${state.metrics.ups} ups`; }, 1000);
setInterval(() => { checkFlow(); renderAlerts(); }, 800);

// alerts callbacks
state.alerts.onChange = () => { renderAlerts(); save(); };
state.alerts.onFire = (text, kind) => toast(text, kind === "up" ? "up" : kind === "down" ? "down" : "flow");

// deep-link (overrides persisted for this load)
(function () { const p = new URLSearchParams(location.search);
  const sy = p.get("symbol"); if (sy) { state.symbol = sy; [...$("symbol").options].forEach((o) => o.selected = o.value === sy); }
  const tf = p.get("tf"); if (tf) { state.interval = tf; document.querySelectorAll("#tf-seg button").forEach((x) => x.classList.toggle("on", x.dataset.tf === tf)); }
  const ty = p.get("type"); if (ty) { state.type = ty; document.querySelectorAll("#type-seg button").forEach((x) => x.classList.toggle("on", x.dataset.type === ty)); }
  if (p.get("heatmap") === "1") { state.panes.heatmap = true; document.querySelector('#pane-chips [data-pane="heatmap"]').classList.add("on"); }
})();

// boot
load();
fetch("/api/config").then((r) => r.json()).then((c) => { if (c.version) $("st-ver").textContent = c.version; }).catch(() => {});
document.querySelectorAll("#pane-chips .chip").forEach((b) => b.classList.toggle("on", !!state.panes[b.dataset.pane]));
document.querySelector(".dock-panel.dom").style.display = state.panes.dom ? "" : "none";
$("heat-legend").classList.toggle("hidden", !state.panes.heatmap);
if (state.tab === "alerts") { document.querySelectorAll(".dp-tab").forEach((x) => x.classList.toggle("on", x.dataset.tab === "alerts")); $("tab-tape").classList.add("hidden"); $("tab-alerts").classList.remove("hidden"); }
renderAlerts();
loadSeed();
