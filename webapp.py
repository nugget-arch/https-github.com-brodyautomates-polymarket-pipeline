#!/usr/bin/env python3
"""
Polymarket Pipeline — Web Dashboard
Browser version of the Bloomberg Terminal-style dashboard. Runs the real
pipeline on a background loop and serves live state over HTTP.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

import config
import logger
from scraper import scrape_all
from markets import fetch_active_markets, filter_by_categories
from scorer import score_market, filter_news_for_market
from edge import detect_edge
from executor import execute_trade

app = Flask(__name__)


class PipelineState:
    """Track live pipeline state across scan cycles. Guarded by `lock`."""

    def __init__(self):
        self.lock = threading.Lock()
        self.run_number = 0
        self.markets_scanned = 0
        self.headlines_found = 0
        self.signals_found = 0
        self.trades_executed = 0
        self.latest_signals: list[dict] = []
        self.latest_markets: list = []
        self.latest_headlines: list[dict] = []
        self.latest_scores: dict = {}
        self.scanning = False
        self.scan_status = "Initializing..."
        self.last_error: str | None = None


state = PipelineState()


def run_scan_cycle():
    """Execute one full pipeline scan and update shared state."""
    with state.lock:
        state.run_number += 1
        state.scanning = True
        state.scan_status = "Scraping news..."

    try:
        news = scrape_all()
        all_markets = fetch_active_markets(limit=100)
        markets = filter_by_categories(all_markets)[:12]

        with state.lock:
            state.headlines_found = len(news)
            state.latest_headlines = [
                {"headline": n.headline, "source": n.source, "age": f"{n.age_hours():.1f}h"}
                for n in news[:8]
            ]
            state.markets_scanned = len(markets)
            state.latest_markets = markets
            state.scan_status = "Scoring markets..."

        signals = []
        scores = {}
        for i, market in enumerate(markets):
            with state.lock:
                state.scan_status = f"Scoring [{i + 1}/{len(markets)}] {market.question[:40]}..."

            relevant = filter_news_for_market(market, news)
            result = score_market(market, relevant)
            scores[market.condition_id] = result

            headlines_str = "\n".join(n.headline for n in relevant[:5])
            signal = detect_edge(market, result["confidence"], result["reasoning"], headlines_str)
            if signal:
                trade_result = execute_trade(signal)
                signals.append({"market": market, "score": result, "trade": trade_result})
            time.sleep(0.3)

        with state.lock:
            state.latest_signals = signals
            state.latest_scores = scores
            state.signals_found = len(signals)
            state.trades_executed = len(signals)
            state.last_error = None

    except Exception as e:
        with state.lock:
            state.last_error = f"{type(e).__name__}: {e}"
    finally:
        with state.lock:
            state.scanning = False
            state.scan_status = "Idle — waiting for next cycle"


def scan_loop(interval: float):
    while True:
        run_scan_cycle()
        time.sleep(interval)


def serialize_state() -> dict:
    """Build the JSON payload the frontend polls."""
    stats = logger.get_trade_stats()
    trades = logger.get_recent_trades(limit=100)
    daily_spent = abs(logger.get_daily_pnl())

    by_status = stats["by_status"]
    dry_runs = by_status.get("dry_run", 0)
    executed = by_status.get("executed", 0)
    errors = sum(v for k, v in by_status.items() if k.startswith("error"))

    total_wagered = sum(t.get("amount_usd", 0) for t in trades)
    avg_edge = sum(t.get("edge", 0) for t in trades) / max(len(trades), 1) * 100
    best_edge = max((t.get("edge", 0) for t in trades), default=0) * 100

    with state.lock:
        signal_questions = {s["market"].question for s in state.latest_signals}

        scanner_rows = []
        for sig in state.latest_signals[:5]:
            m, t = sig["market"], sig["trade"]
            scanner_rows.append({
                "market": m.question[:60],
                "market_price": round(m.yes_price, 2),
                "claude_score": round(sig["score"].get("confidence", 0.5), 2),
                "edge": round(t["edge"] * 100, 1),
                "side": t["side"],
                "bet": round(t["amount"], 2),
                "status": t.get("status", "dry_run"),
                "is_signal": True,
            })

        for m in state.latest_markets:
            if m.question in signal_questions or len(scanner_rows) >= 8:
                continue
            score = state.latest_scores.get(m.condition_id, {})
            confidence = score.get("confidence", 0.5)
            edge = abs(confidence - m.yes_price)
            scanner_rows.append({
                "market": m.question[:60],
                "market_price": round(m.yes_price, 2),
                "claude_score": round(confidence, 2),
                "edge": round(edge * 100, 1),
                "side": None,
                "bet": None,
                "status": "no edge",
                "is_signal": False,
            })

        payload = {
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "mode": "LIVE" if not config.DRY_RUN else "DRY RUN",
            "status": {
                "scanning": state.scanning,
                "run_number": state.run_number,
                "activity": state.scan_status,
                "markets_scanned": state.markets_scanned,
                "headlines_found": state.headlines_found,
                "signals_found": state.signals_found,
                "trades_executed": state.trades_executed,
                "edge_threshold": config.EDGE_THRESHOLD,
                "max_bet": config.MAX_BET_USD,
                "daily_limit": config.DAILY_LOSS_LIMIT_USD,
                "last_error": state.last_error,
            },
            "latest_headline": state.latest_headlines[0] if state.latest_headlines else None,
            "scanner": scanner_rows,
        }

    payload["performance"] = {
        "total_signals": stats["total_trades"],
        "dry_runs": dry_runs,
        "executed": executed,
        "errors": errors,
        "daily_exposure": round(daily_spent, 2),
        "total_wagered": round(total_wagered, 2),
        "avg_edge": round(avg_edge, 1),
        "best_edge": round(best_edge, 1),
    }
    payload["trades"] = [{
        "time": t["created_at"][:16],
        "market": t["market_question"][:60],
        "side": t["side"],
        "bet": round(t["amount_usd"], 2),
        "edge": round(t["edge"] * 100, 1),
        "claude_score": round(t["claude_score"], 2),
        "market_price": round(t["market_price"], 2),
        "status": t["status"],
    } for t in trades[:15]]

    return payload


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(serialize_state())


def run_web(scan_interval: float = 60.0, host: str = "127.0.0.1", port: int = 8000):
    """Launch the web dashboard: background scan loop + Flask server."""
    thread = threading.Thread(target=scan_loop, args=(scan_interval,), daemon=True)
    thread.start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    run_web(scan_interval=interval)
