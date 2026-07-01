const REFRESH_MS = 5000;

function el(tag, opts = {}) {
  const node = document.createElement(tag);
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.className) node.className = opts.className;
  return node;
}

function kvRow(label, value, valueClass) {
  const tr = document.createElement("tr");
  tr.appendChild(el("td", { text: label }));
  const valTd = el("td", { text: value });
  if (valueClass) valTd.className = valueClass;
  tr.appendChild(valTd);
  return tr;
}

function statusClass(status) {
  if (status === "dry_run") return "status-dry";
  if (status === "executed") return "status-filled";
  if (typeof status === "string" && status.startsWith("error")) return "status-error";
  return "status-muted";
}

function statusLabel(status) {
  if (status === "dry_run") return "DRY RUN";
  if (status === "executed") return "FILLED";
  if (status === "rejected_daily_limit") return "LIMIT";
  if (status === "no edge") return "no edge";
  return status;
}

function renderStatus(data) {
  const body = document.getElementById("status-body");
  body.innerHTML = "";
  const s = data.status;
  const dot = s.scanning ? "◌ SCANNING" : (s.run_number > 0 ? "● ACTIVE" : "○ STARTING");
  body.appendChild(kvRow("Pipeline", dot));
  body.appendChild(kvRow("Scan Cycle", s.run_number > 0 ? `#${s.run_number}` : "—"));
  body.appendChild(kvRow("Activity", s.activity));
  body.appendChild(kvRow("Markets Scanned", s.run_number > 0 ? s.markets_scanned : "—"));
  body.appendChild(kvRow("Headlines Found", s.run_number > 0 ? s.headlines_found : "—"));
  body.appendChild(kvRow("Signals / Trades", s.run_number > 0 ? `${s.signals_found} / ${s.trades_executed}` : "— / —"));
  body.appendChild(kvRow("Edge Threshold", `>= ${(s.edge_threshold * 100).toFixed(0)}%`));
  body.appendChild(kvRow("Max Bet", `$${s.max_bet.toFixed(2)}`));
  body.appendChild(kvRow("Daily Limit", `$${s.daily_limit.toFixed(2)}`));
  body.appendChild(kvRow("Mode", data.mode));
  if (s.last_error) {
    body.appendChild(kvRow("Last Error", s.last_error, "status-error"));
  }
}

function renderPerformance(data) {
  const body = document.getElementById("performance-body");
  body.innerHTML = "";
  const p = data.performance;
  body.appendChild(kvRow("Total Signals", p.total_signals));
  body.appendChild(kvRow("Dry Runs", p.dry_runs, "status-dry"));
  body.appendChild(kvRow("Executed", p.executed, "status-filled"));
  if (p.errors) body.appendChild(kvRow("Errors", p.errors, "status-error"));
  body.appendChild(kvRow("Daily Exposure", `$${p.daily_exposure.toFixed(2)}`));
  body.appendChild(kvRow("Total Wagered", `$${p.total_wagered.toFixed(2)}`));
  body.appendChild(kvRow("Avg Edge", `${p.avg_edge.toFixed(1)}%`));
  if (data.trades.length) body.appendChild(kvRow("Best Edge", `${p.best_edge.toFixed(1)}%`));
}

function renderScanner(data) {
  const body = document.getElementById("scanner-body");
  body.innerHTML = "";
  if (!data.scanner.length) {
    const tr = document.createElement("tr");
    const td = el("td", { text: "Waiting for first scan..." });
    td.className = "status-muted";
    td.colSpan = 7;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of data.scanner) {
    const tr = document.createElement("tr");
    if (!row.is_signal) tr.className = "row-dim";

    tr.appendChild(el("td", { text: row.market }));
    tr.appendChild(el("td", { text: row.market_price.toFixed(2), className: "num" }));
    tr.appendChild(el("td", { text: row.claude_score.toFixed(2), className: "num" }));
    tr.appendChild(el("td", { text: `${row.edge.toFixed(0)}%`, className: "num" }));

    const sideTd = el("td", { text: row.side || "—" });
    if (row.side === "YES") sideTd.className = "side-yes";
    else if (row.side === "NO") sideTd.className = "side-no";
    tr.appendChild(sideTd);

    tr.appendChild(el("td", { text: row.bet != null ? `$${row.bet.toFixed(0)}` : "—", className: "num" }));

    const statusTd = el("td", { text: statusLabel(row.status) });
    statusTd.className = statusClass(row.status);
    tr.appendChild(statusTd);

    body.appendChild(tr);
  }
}

function renderTrades(data) {
  const body = document.getElementById("trades-body");
  body.innerHTML = "";
  if (!data.trades.length) {
    const tr = document.createElement("tr");
    const td = el("td", { text: "No trades yet — pipeline scanning..." });
    td.className = "status-muted";
    td.colSpan = 8;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const t of data.trades) {
    const tr = document.createElement("tr");
    tr.appendChild(el("td", { text: t.time }));
    tr.appendChild(el("td", { text: t.market }));

    const sideTd = el("td", { text: t.side });
    sideTd.className = t.side === "YES" ? "side-yes" : "side-no";
    tr.appendChild(sideTd);

    tr.appendChild(el("td", { text: `$${t.bet.toFixed(2)}`, className: "num" }));
    tr.appendChild(el("td", { text: `${t.edge.toFixed(0)}%`, className: "num" }));
    tr.appendChild(el("td", { text: t.claude_score.toFixed(2), className: "num" }));
    tr.appendChild(el("td", { text: t.market_price.toFixed(2), className: "num" }));

    const statusTd = el("td", { text: statusLabel(t.status) });
    statusTd.className = statusClass(t.status);
    tr.appendChild(statusTd);

    body.appendChild(tr);
  }
}

function renderFooter(data) {
  document.getElementById("clock").textContent = data.now;
  const headlineEl = document.getElementById("headline");
  if (data.latest_headline) {
    headlineEl.textContent = `> ${data.latest_headline.source}: ${data.latest_headline.headline}`;
  } else {
    headlineEl.textContent = "Waiting for news feed...";
  }
  document.getElementById("footer-stats").textContent =
    `${data.mode}  |  Signals: ${data.performance.total_signals}`;
}

async function refresh() {
  try {
    const resp = await fetch("/api/state");
    if (!resp.ok) return;
    const data = await resp.json();
    renderStatus(data);
    renderPerformance(data);
    renderScanner(data);
    renderTrades(data);
    renderFooter(data);
  } catch (err) {
    console.error("dashboard refresh failed", err);
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
