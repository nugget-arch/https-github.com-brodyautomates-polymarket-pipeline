/* Order Flow Terminal — live footprint chart with pro detections.
   Seed (real recent footprint) comes from our server; the live WebSocket to
   Binance keeps it updating trade-by-trade. Rendering is a footprint/cluster
   chart (bid x ask per price level) with imbalance / absorption / iceberg
   overlays, a delta strip and a cumulative-delta (CVD) subpanel. */

import {
  CFG, newCandle, applyTrade, candleFromSeed, sortedLevels, analyze,
} from "./footprint.js";

const $ = (id) => document.getElementById(id);
const canvas = $("chart");
const ctx = canvas.getContext("2d");

const C = {
  bg: "#070a0e", grid: "#141b26", gridSoft: "#0f1520", axis: "#6b7686",
  up: "#2fbf71", down: "#f0524a",
  buy: "#2fbf71", sell: "#f0524a",
  askText: "#7ff0b4", bidText: "#ff9c96",
  poc: "#ffb020", vaLine: "rgba(109,139,255,.5)", vaFill: "rgba(109,139,255,.06)",
  ice: "#35c9e0", absorb: "#c77dff",
  cvdUp: "#2fbf71", cvdDn: "#f0524a",
};

const state = {
  seed: null,
  basetick: 1,
  intervalMs: 60000,
  symbol: "BTCUSDT",
  interval: "1m",
  candles: [],          // ordered oldest->newest, base-resolution footprint
  ohlc: [],             // full-window OHLC for CVD/context
  va: { vpoc: 0, vah: 0, val: 0 },
  ws: null,
  wsTries: 0,
  pollTimer: null,
  dirty: false,
  hover: -1,
  toggles: { numbers: true, imbalance: true, absorption: true, iceberg: true },
  signals: [],          // recent detection feed
  cvd: [],              // cumulative delta per visible candle
  layout: null,
};

// ------------------------------------------------------------- helpers ----
const nf = (n, d = 2) => Number(n).toLocaleString("en-US",
  { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (n, d = 2) => (n >= 0 ? "+" : "") + nf(n, d);

function volFmt(v) {
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  if (v >= 100) return v.toFixed(0);
  if (v >= 10) return v.toFixed(1);
  return v.toFixed(2);
}
function hhmm(t) {
  const d = new Date(t);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

function setConn(cls, msg) {
  $("conn").className = "conn " + cls;
  if (msg) $("status").textContent = msg;
}
function markDirty() {
  if (state.dirty) return;
  state.dirty = true;
  requestAnimationFrame(() => { state.dirty = false; draw(); });
}

// ---------------------------------------------------------------- seed ----
async function loadSeed() {
  state.symbol = $("symbol").value;
  state.interval = $("interval").value;
  const n = $("candles").value;
  setConn("wait", "Cargando footprint real…");
  try {
    const r = await fetch(
      `/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=90&fp=${n}`);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    state.seed = d;
    state.basetick = d.basetick;
    state.intervalMs = d.intervalMs;
    state.ohlc = d.candles;
    state.va = { vpoc: d.vpoc, vah: d.vah, val: d.val };
    state.candles = d.footprints.map((fp) => candleFromSeed(fp, d.basetick));
    state.signals = [];
    rebuildSignals();
    $("hdr-symbol").textContent = `${state.symbol} · ${state.interval}`;
    updateHeader(d.lastPrice);
    if (state.candles.length) updateLive(state.candles[state.candles.length - 1]);
    resize();
    setConn("wait", "Footprint listo · conectando stream…");
    connectWS();
  } catch (e) {
    setConn("off", "Error seed: " + e.message);
  }
}

// ------------------------------------------------------ live websocket ----
function wsUrls() {
  const s = state.symbol.toLowerCase();
  const streams = `${s}@aggTrade/${s}@kline_${state.interval}`;
  return [
    `wss://data-stream.binance.vision/stream?streams=${streams}`,
    `wss://stream.binance.com:9443/stream?streams=${streams}`,
  ];
}

function connectWS() {
  closeWS();
  const url = wsUrls()[state.wsTries % 2];
  let opened = false;
  let ws;
  try { ws = new WebSocket(url); }
  catch { return startPolling(); }
  state.ws = ws;

  const failTimer = setTimeout(() => { if (!opened) { try { ws.close(); } catch {} } }, 4500);

  ws.onopen = () => {
    opened = true; state.wsTries = 0; clearTimeout(failTimer);
    stopPolling();
    setConn("on", "En vivo · WebSocket");
  };
  ws.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    const d = msg.data || msg;
    if (d.e === "aggTrade") onAggTrade(d);
    else if (d.e === "kline") onKline(d.k);
  };
  ws.onclose = () => {
    clearTimeout(failTimer);
    if (!opened) { state.wsTries++; }
    if (state.wsTries >= 2 && !opened) { setConn("off", "WS bloqueado · usando polling REST"); return startPolling(); }
    setConn("wait", "Reconectando stream…");
    setTimeout(connectWS, 1200);
  };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
function closeWS() { if (state.ws) { try { state.ws.onclose = null; state.ws.close(); } catch {} state.ws = null; } }

function currentBucket(t) { return Math.floor(t / state.intervalMs) * state.intervalMs; }

function ensureCandle(bucketT, price) {
  const last = state.candles[state.candles.length - 1];
  if (last && last.t === bucketT) return last;
  if (last && bucketT > last.t) { last.finished = true; }
  const c = newCandle(bucketT, price);
  state.candles.push(c);
  const maxKeep = Math.max(60, parseInt($("candles").value, 10) + 6);
  if (state.candles.length > maxKeep) state.candles.shift();
  rebuildSignals();
  return c;
}

function onAggTrade(d) {
  const price = parseFloat(d.p), qty = parseFloat(d.q);
  const bucket = currentBucket(d.T);
  const c = ensureCandle(bucket, price);
  applyTrade(c, price, qty, d.m, state.basetick);   // d.m === true => aggressive sell
  updateHeader(price);
  updateLive(c);
  markDirty();
}

function onKline(k) {
  const bucket = parseInt(k.t, 10);
  const c = ensureCandle(bucket, parseFloat(k.o));
  c.o = parseFloat(k.o); c.h = parseFloat(k.h); c.l = parseFloat(k.l); c.c = parseFloat(k.c);
  if (k.x) { c.finished = true; rebuildSignals(); }
  updateHeader(parseFloat(k.c));
  markDirty();
}

// -------------------------------------------------- REST polling fallback -
function startPolling() {
  if (state.pollTimer) return;
  const tick = async () => {
    try {
      const r = await fetch(
        `/api/seed?symbol=${state.symbol}&interval=${state.interval}&candles=90&fp=${$("candles").value}`);
      const d = await r.json();
      if (!d.error) {
        state.basetick = d.basetick; state.va = { vpoc: d.vpoc, vah: d.vah, val: d.val };
        state.ohlc = d.candles;
        state.candles = d.footprints.map((fp) => candleFromSeed(fp, d.basetick));
        rebuildSignals();
        updateHeader(d.lastPrice);
        if (state.candles.length) updateLive(state.candles[state.candles.length - 1]);
        markDirty();
      }
    } catch {}
  };
  state.pollTimer = setInterval(tick, 4000);
  tick();
}
function stopPolling() { if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; } }

// --------------------------------------------------- display aggregation --
/** Aggregate a base-resolution candle into `k` display ticks. */
function aggregate(candle, k) {
  if (k <= 1) return candle;
  const levels = new Map();
  for (const [idx, cell] of candle.levels) {
    const di = Math.floor(idx / k);
    let c = levels.get(di);
    if (!c) { c = { bid: 0, ask: 0 }; levels.set(di, c); }
    c.bid += cell.bid; c.ask += cell.ask;
  }
  return { ...candle, levels, _k: k };
}

// ------------------------------------------------------------- signals ----
function rebuildSignals() {
  const k = state.layout ? state.layout.k : 1;
  const feed = [];
  for (const base of state.candles) {
    const c = aggregate(base, k);
    const a = analyze(c, sigCfg(c));
    const dt = state.basetick * k;
    for (const st of a.stacks) {
      feed.push({
        kind: st.dir, type: "stacked",
        price: (st.dir === "buy" ? st.to : st.from) * dt,
        detail: `Stacked ${st.dir === "buy" ? "compra" : "venta"} ×${st.count}`,
        t: base.t,
      });
    }
    for (const ab of a.absorption) {
      feed.push({
        kind: "absorb", type: "absorption", price: ab.idx * dt,
        detail: `Absorción ${ab.side === "buy" ? "de compras" : "de ventas"} (${volFmt(ab.vol)})`,
        t: base.t,
      });
    }
    for (const ic of a.icebergs) {
      feed.push({
        kind: "ice", type: "iceberg", price: ic.idx * dt,
        detail: `Iceberg ${(ic.share * 100).toFixed(0)}% del vol (${volFmt(ic.vol)})`,
        t: base.t,
      });
    }
  }
  feed.sort((x, y) => y.t - x.t || 0);
  state.signals = feed.slice(0, 40);
  renderSignals();
}

function sigCfg(c) {
  // adapt the "min volume to count" to the candle so tiny ticks don't spam
  const vols = [...c.levels.values()].map((x) => x.bid + x.ask);
  const mean = vols.reduce((a, b) => a + b, 0) / (vols.length || 1);
  return { ...CFG, imbalanceMinVol: mean * 0.5 };
}

function renderSignals() {
  const el = $("sig-list");
  $("sig-count").textContent = state.signals.length;
  if (!state.signals.length) { el.innerHTML = '<div class="sig-empty">Sin señales aún…</div>'; return; }
  const icons = { buy: "▲", sell: "▼", absorb: "◆", ice: "❄" };
  el.innerHTML = state.signals.map((s) => {
    const cls = s.kind === "buy" ? "buy" : s.kind === "sell" ? "sell" : s.kind;
    return `<div class="sig ${cls}">
      <div class="ic">${icons[s.kind] || "•"}</div>
      <div class="tx">${s.detail}<small>${nf(s.price, 1)}</small></div>
      <div class="tm">${hhmm(s.t)}</div>
    </div>`;
  }).join("");
}

// ------------------------------------------------------------ header/live -
function updateHeader(price) {
  $("hdr-price").textContent = nf(price, 2);
  const first = state.ohlc.length ? state.ohlc[0].o : price;
  const chg = ((price - first) / first) * 100;
  const el = $("hdr-chg");
  el.textContent = sgn(chg, 2) + "%";
  el.className = "hchg " + (chg >= 0 ? "pos" : "neg");
}

function updateLive(c) {
  $("l-price").textContent = nf(c.c, 2);
  const de = $("l-delta"); de.textContent = sgn(c.delta, 2); de.className = c.delta >= 0 ? "pos" : "neg";
  $("l-buy").textContent = nf(c.buy, 2);
  $("l-sell").textContent = nf(c.sell, 2);
  const cvd = state.candles.reduce((a, x) => a + x.delta, 0);
  const cv = $("l-cvd"); cv.textContent = sgn(cvd, 1); cv.className = cvd >= 0 ? "pos" : "neg";
  $("l-va").textContent = `${nf(state.va.vpoc, 0)} / ${nf(state.va.vah, 0)} / ${nf(state.va.val, 0)}`;
}

// ------------------------------------------------------------- geometry ---
const AX_W = 62, PROFILE_W = 66, DELTA_H = 46, CVD_H = 42, TIME_H = 18, TOP = 8;

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function computeLayout() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const n = Math.min(state.candles.length, parseInt($("candles").value, 10));
  const vis = state.candles.slice(state.candles.length - n);
  if (!vis.length) return null;

  const plotL = PROFILE_W;
  const plotR = w - AX_W;
  const plotT = TOP;
  const plotB = h - TIME_H - CVD_H - DELTA_H;

  let lo = Infinity, hi = -Infinity;
  for (const c of vis) { if (c.l < lo) lo = c.l; if (c.h > hi) hi = c.h; }
  const padPx = (hi - lo) * 0.02;
  lo -= padPx; hi += padPx;
  if (!(hi > lo)) { hi = lo + state.basetick * 10; }

  const availH = plotB - plotT;
  const desiredRows = Math.min(70, Math.max(8, Math.floor(availH / 13)));
  const rawTicks = (hi - lo) / state.basetick;
  const k = Math.max(1, Math.ceil(rawTicks / desiredRows));
  const dTick = state.basetick * k;
  const rowLo = Math.floor(lo / dTick);
  const rowHi = Math.ceil(hi / dTick);
  const rows = Math.max(1, rowHi - rowLo);
  const rowH = availH / rows;

  const colW = (plotR - plotL) / n;
  const y = (price) => plotB - ((price - rowLo * dTick) / ((rowHi - rowLo) * dTick)) * availH;
  const rowY = (di) => plotB - (di - rowLo) * rowH;   // top edge of a display row

  return { w, h, plotL, plotR, plotT, plotB, vis, n, lo, hi, k, dTick,
           rowLo, rowHi, rows, rowH, colW, y, rowY };
}

// ---------------------------------------------------------------- draw ----
function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, w, h);
  if (!state.candles.length) return;

  const L = computeLayout();
  state.layout = L;
  if (!L) return;

  drawValueArea(L);
  drawGrid(L);
  drawSessionProfile(L);
  drawClusters(L);
  drawLevels(L);
  drawDeltaStrip(L);
  drawCVD(L);
  drawPriceAxis(L);
  drawTimeAxis(L);
  drawLastPrice(L);
}

function drawGrid(L) {
  ctx.strokeStyle = C.gridSoft; ctx.lineWidth = 1;
  for (let i = 0; i <= L.n; i++) {
    const x = Math.round(L.plotL + i * L.colW) + 0.5;
    ctx.beginPath(); ctx.moveTo(x, L.plotT); ctx.lineTo(x, L.plotB); ctx.stroke();
  }
}

function drawValueArea(L) {
  const yH = L.y(state.va.vah), yL = L.y(state.va.val);
  ctx.fillStyle = C.vaFill;
  ctx.fillRect(L.plotL, Math.min(yH, yL), L.plotR - L.plotL, Math.abs(yL - yH));
}

function drawSessionProfile(L) {
  // aggregate all visible candles into one buy/sell profile by display row
  const prof = new Map();
  let maxV = 0;
  for (const base of L.vis) {
    const c = aggregate(base, L.k);
    for (const [di, cell] of c.levels) {
      let p = prof.get(di); if (!p) { p = { bid: 0, ask: 0 }; prof.set(di, p); }
      p.bid += cell.bid; p.ask += cell.ask;
      maxV = Math.max(maxV, p.bid + p.ask);
    }
  }
  maxV = maxV || 1;
  for (const [di, cell] of prof) {
    const yTop = L.rowY(di + 1), hgt = Math.max(1, L.rowH - 0.5);
    const bw = (cell.ask / maxV) * (PROFILE_W - 6);
    const sw = (cell.bid / maxV) * (PROFILE_W - 6);
    ctx.fillStyle = C.buy; ctx.globalAlpha = 0.5;
    ctx.fillRect(PROFILE_W - bw, yTop, bw, hgt);
    ctx.fillStyle = C.sell; ctx.globalAlpha = 0.5;
    ctx.fillRect(PROFILE_W - bw - sw, yTop, sw, hgt);
    ctx.globalAlpha = 1;
  }
  ctx.strokeStyle = C.grid; ctx.beginPath();
  ctx.moveTo(PROFILE_W + 0.5, L.plotT); ctx.lineTo(PROFILE_W + 0.5, L.plotB); ctx.stroke();
}

function drawClusters(L) {
  const showNums = state.toggles.numbers && L.colW >= 44 && L.rowH >= 10;
  ctx.textBaseline = "middle";
  ctx.font = `${Math.max(7.5, Math.min(10, L.rowH - 2))}px ui-monospace, monospace`;

  L.vis.forEach((base, ci) => {
    const c = aggregate(base, L.k);
    const a = analyze(c, sigCfg(c));
    const x0 = L.plotL + ci * L.colW;
    const midX = x0 + L.colW / 2;
    // per-candle max level vol for shading
    let cmax = 1;
    for (const cell of c.levels.values()) cmax = Math.max(cmax, cell.bid + cell.ask);

    // wick + body (thin, behind numbers)
    const up = c.c >= c.o;
    ctx.strokeStyle = up ? C.up : C.down; ctx.globalAlpha = 0.5; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(midX, L.y(c.h)); ctx.lineTo(midX, L.y(c.l)); ctx.stroke();
    ctx.globalAlpha = 1;

    for (const [di, cell] of c.levels) {
      const yTop = L.rowY(di + 1);
      const yMid = yTop + L.rowH / 2;
      if (yTop > L.plotB || yTop + L.rowH < L.plotT) continue;
      const vol = cell.bid + cell.ask;
      const intensity = vol / cmax;
      const halfW = (L.colW - 2) / 2;

      // bid (left, sell aggr) / ask (right, buy aggr) shaded cells
      ctx.fillStyle = C.sell; ctx.globalAlpha = 0.10 + 0.28 * (cell.bid / cmax);
      ctx.fillRect(x0 + 1, yTop + 0.5, halfW, L.rowH - 1);
      ctx.fillStyle = C.buy; ctx.globalAlpha = 0.10 + 0.28 * (cell.ask / cmax);
      ctx.fillRect(midX, yTop + 0.5, halfW, L.rowH - 1);
      ctx.globalAlpha = 1;

      // imbalance highlight
      if (state.toggles.imbalance) {
        const dir = a.flags.get(di);
        if (dir === "buy") {
          ctx.strokeStyle = C.buy; ctx.lineWidth = 1.5;
          ctx.strokeRect(midX + 0.5, yTop + 1, halfW - 1, L.rowH - 2);
        } else if (dir === "sell") {
          ctx.strokeStyle = C.sell; ctx.lineWidth = 1.5;
          ctx.strokeRect(x0 + 1.5, yTop + 1, halfW - 1, L.rowH - 2);
        }
      }

      if (showNums && vol > 0) {
        ctx.textAlign = "right";
        ctx.fillStyle = cell.bid > 0 ? C.bidText : "#3a4453";
        ctx.fillText(volFmt(cell.bid), midX - 3, yMid);
        ctx.textAlign = "left";
        ctx.fillStyle = cell.ask > 0 ? C.askText : "#3a4453";
        ctx.fillText(volFmt(cell.ask), midX + 3, yMid);
      } else if (!showNums) {
        // heatmap-only mode: a stronger fill already drawn; add POC tick
      }
    }

    // stacked imbalance bracket
    if (state.toggles.imbalance) {
      for (const st of a.stacks) {
        const yA = L.rowY(st.to + 1), yB = L.rowY(st.from);
        ctx.strokeStyle = st.dir === "buy" ? C.buy : C.sell;
        ctx.lineWidth = 2.5;
        const bx = st.dir === "buy" ? x0 + L.colW - 2 : x0 + 2;
        ctx.beginPath(); ctx.moveTo(bx, yA); ctx.lineTo(bx, yB); ctx.stroke();
      }
    }

    // POC outline
    if (a.poc != null) {
      const yTop = L.rowY(a.poc + 1);
      ctx.strokeStyle = C.poc; ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 1, yTop + 0.5, L.colW - 2, L.rowH - 1);
    }

    // absorption marker
    if (state.toggles.absorption) {
      for (const ab of a.absorption) {
        const yMid = L.rowY(ab.idx + 1) + L.rowH / 2;
        badge(midX, yMid, C.absorb, "A");
      }
    }
    // iceberg marker
    if (state.toggles.iceberg) {
      for (const ic of a.icebergs) {
        const yMid = L.rowY(ic.idx + 1) + L.rowH / 2;
        badge(x0 + 9, yMid, C.ice, "❄");
      }
    }

    // hover highlight
    if (state.hover === ci) {
      ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 0.5, L.plotT, L.colW, L.plotB - L.plotT);
    }
  });
  ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
}

function badge(x, y, color, txt) {
  ctx.beginPath(); ctx.fillStyle = color; ctx.globalAlpha = 0.92;
  ctx.arc(x, y, 6.5, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  ctx.fillStyle = "#0a0e14"; ctx.font = "bold 8px ui-monospace, monospace";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(txt, x, y + 0.5);
  ctx.textAlign = "left"; ctx.textBaseline = "middle";
}

function levelLine(L, price, color, label, dash) {
  const yy = Math.round(L.y(price)) + 0.5;
  if (yy < L.plotT || yy > L.plotB) return;
  ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(dash ? [5, 4] : []);
  ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "left";
  ctx.fillText(label, L.plotL + 3, yy - 3);
}
function drawLevels(L) {
  levelLine(L, state.va.vah, C.vaLine, "VAH", true);
  levelLine(L, state.va.val, C.vaLine, "VAL", true);
  levelLine(L, state.va.vpoc, C.poc, "vPOC", false);
}

function drawDeltaStrip(L) {
  const y0 = L.plotB, yH = DELTA_H;
  ctx.fillStyle = "#0a0e14"; ctx.fillRect(L.plotL, y0, L.plotR - L.plotL, yH);
  let maxAbs = 1;
  for (const c of L.vis) maxAbs = Math.max(maxAbs, Math.abs(c.delta));
  const mid = y0 + yH * 0.55;
  ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "center";
  L.vis.forEach((c, ci) => {
    const x0 = L.plotL + ci * L.colW;
    const bh = (Math.abs(c.delta) / maxAbs) * (yH * 0.4);
    ctx.fillStyle = c.delta >= 0 ? C.buy : C.sell;
    if (c.delta >= 0) ctx.fillRect(x0 + 2, mid - bh, L.colW - 4, bh);
    else ctx.fillRect(x0 + 2, mid, L.colW - 4, bh);
    if (L.colW >= 34) {
      ctx.fillStyle = c.delta >= 0 ? C.askText : C.bidText;
      ctx.fillText(sgn(c.delta, c.delta > 10 || c.delta < -10 ? 0 : 1).replace("+", ""),
        x0 + L.colW / 2, y0 + yH - 4);
    }
  });
  ctx.fillStyle = C.axis; ctx.textAlign = "left";
  ctx.fillText("Δ", 6, y0 + 12);
  ctx.strokeStyle = C.grid; ctx.beginPath();
  ctx.moveTo(L.plotL, y0 + 0.5); ctx.lineTo(L.plotR, y0 + 0.5); ctx.stroke();
}

function drawCVD(L) {
  const y0 = L.plotB + DELTA_H, yH = CVD_H;
  ctx.fillStyle = C.bg; ctx.fillRect(L.plotL, y0, L.plotR - L.plotL, yH);
  // cumulative delta across visible candles
  let cum = 0; const pts = [];
  for (const c of L.vis) { cum += c.delta; pts.push(cum); }
  let mn = Math.min(0, ...pts), mx = Math.max(0, ...pts);
  if (mx === mn) { mx += 1; mn -= 1; }
  const yy = (v) => y0 + yH - ((v - mn) / (mx - mn)) * (yH - 8) - 4;
  // zero line
  ctx.strokeStyle = C.grid; ctx.setLineDash([3, 3]); ctx.beginPath();
  ctx.moveTo(L.plotL, yy(0)); ctx.lineTo(L.plotR, yy(0)); ctx.stroke(); ctx.setLineDash([]);
  ctx.lineWidth = 1.6; ctx.beginPath();
  pts.forEach((v, i) => {
    const x = L.plotL + i * L.colW + L.colW / 2;
    if (i === 0) ctx.moveTo(x, yy(v)); else ctx.lineTo(x, yy(v));
  });
  ctx.strokeStyle = pts[pts.length - 1] >= 0 ? C.cvdUp : C.cvdDn; ctx.stroke();
  ctx.fillStyle = C.axis; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "left";
  ctx.fillText("CVD", 6, y0 + 12);
}

function drawPriceAxis(L) {
  ctx.fillStyle = C.axis; ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "left";
  const steps = 8;
  for (let i = 0; i <= steps; i++) {
    const p = L.rowLo * L.dTick + (i / steps) * (L.rowHi - L.rowLo) * L.dTick;
    const yy = Math.round(L.y(p));
    if (yy < L.plotT || yy > L.plotB) continue;
    ctx.strokeStyle = C.gridSoft; ctx.beginPath();
    ctx.moveTo(L.plotL, yy + 0.5); ctx.lineTo(L.plotR, yy + 0.5); ctx.stroke();
    ctx.fillStyle = C.axis; ctx.fillText(nf(p, p > 1000 ? 0 : 2), L.plotR + 5, yy + 3);
  }
}

function drawTimeAxis(L) {
  ctx.fillStyle = C.axis; ctx.font = "9px ui-monospace, monospace"; ctx.textAlign = "center";
  const y = L.h - 5;
  const step = Math.ceil(L.n / 8);
  L.vis.forEach((c, ci) => {
    if (ci % step !== 0) return;
    ctx.fillText(hhmm(c.t), L.plotL + ci * L.colW + L.colW / 2, y);
  });
}

function drawLastPrice(L) {
  const last = state.candles[state.candles.length - 1];
  if (!last) return;
  const yy = Math.round(L.y(last.c)) + 0.5;
  if (yy < L.plotT || yy > L.plotB) return;
  const up = last.c >= last.o;
  ctx.strokeStyle = up ? C.up : C.down; ctx.setLineDash([2, 2]); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(L.plotL, yy); ctx.lineTo(L.plotR, yy); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = up ? C.up : C.down;
  ctx.fillRect(L.plotR, yy - 8, AX_W, 16);
  ctx.fillStyle = "#0a0e14"; ctx.font = "bold 10px ui-monospace, monospace"; ctx.textAlign = "left";
  ctx.fillText(nf(last.c, 2), L.plotR + 4, yy + 3);
}

// -------------------------------------------------------- interaction ----
canvas.addEventListener("mousemove", (e) => {
  const L = state.layout; if (!L) return;
  const rect = canvas.getBoundingClientRect();
  const px = e.clientX - rect.left, py = e.clientY - rect.top;
  const ci = Math.floor((px - L.plotL) / L.colW);
  const tip = $("tooltip");
  if (ci < 0 || ci >= L.n || px > L.plotR || py > L.plotB) { tip.classList.add("hidden"); state.hover = -1; return; }
  state.hover = ci;
  const base = L.vis[ci];
  const c = aggregate(base, L.k);
  const a = analyze(c, sigCfg(c));
  const flags = [];
  if (a.stacks.length) flags.push(`Stacked ×${a.stacks.map((s) => s.count).join(",")}`);
  if (a.absorption.length) flags.push("Absorción");
  if (a.icebergs.length) flags.push("Iceberg");
  tip.innerHTML =
    `<div class="row"><span>${hhmm(base.t)}</span><b>${base.finished ? "" : "· en curso"}</b></div>` +
    `<div class="row"><span>O</span>${nf(base.o, 2)}</div>` +
    `<div class="row"><span>H</span>${nf(base.h, 2)}</div>` +
    `<div class="row"><span>L</span>${nf(base.l, 2)}</div>` +
    `<div class="row"><span>C</span>${nf(base.c, 2)}</div>` +
    `<hr/>` +
    `<div class="row"><span>Buy</span><b class="pos">${nf(base.buy, 2)}</b></div>` +
    `<div class="row"><span>Sell</span><b class="neg">${nf(base.sell, 2)}</b></div>` +
    `<div class="row"><span>Delta</span><b class="${base.delta >= 0 ? "pos" : "neg"}">${sgn(base.delta, 2)}</b></div>` +
    (flags.length ? `<hr/><div class="row"><span>Flags</span><b>${flags.join(" · ")}</b></div>` : "");
  tip.classList.remove("hidden");
  const tw = tip.offsetWidth;
  tip.style.left = Math.min(px + 14, canvas.clientWidth - tw - 8) + "px";
  tip.style.top = Math.max(py - 10, 8) + "px";
  markDirty();
});
canvas.addEventListener("mouseleave", () => { state.hover = -1; $("tooltip").classList.add("hidden"); markDirty(); });

// ------------------------------------------------------------- wiring ----
document.querySelectorAll(".tg").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.tg;
    state.toggles[key] = !state.toggles[key];
    btn.classList.toggle("on", state.toggles[key]);
    markDirty();
  });
});
["symbol", "interval", "candles"].forEach((id) =>
  $(id).addEventListener("change", () => { closeWS(); stopPolling(); state.wsTries = 0; loadSeed(); }));
window.addEventListener("resize", resize);

loadSeed();
