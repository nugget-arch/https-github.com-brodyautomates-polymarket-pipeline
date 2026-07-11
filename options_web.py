#!/usr/bin/env python3
"""
Options Strategy Analyzer — web dashboard.

Serves the analysis produced by options_analyzer.py: thousands of real
call/put strategies scored with probabilistic stats, plus the aggregate
visuals (scatter, histograms, heatmap, payoff diagrams).
"""
from __future__ import annotations

import sys
import threading
import time

from flask import Flask, jsonify, render_template

import options_analyzer

app = Flask(__name__)

_state_lock = threading.Lock()
_state: dict = {
    "scanning": True,
    "activity": "Starting first scan...",
    "result": None,
    "scan_number": 0,
}


def _set_activity(msg: str):
    with _state_lock:
        _state["activity"] = msg


def scan_loop(tickers: list[str] | None, interval: float):
    while True:
        with _state_lock:
            _state["scanning"] = True
        try:
            result = options_analyzer.scan(tickers, on_progress=_set_activity)
            with _state_lock:
                _state["result"] = result
                _state["scan_number"] += 1
                _state["activity"] = "Idle — next scan in %d min" % (interval // 60)
        except Exception as e:
            with _state_lock:
                _state["activity"] = f"Scan failed: {type(e).__name__}: {e}"
        finally:
            with _state_lock:
                _state["scanning"] = False
        time.sleep(interval)


@app.route("/")
def index():
    return render_template("options.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/options")
def api_options():
    with _state_lock:
        return jsonify({
            "scanning": _state["scanning"],
            "activity": _state["activity"],
            "scan_number": _state["scan_number"],
            "result": _state["result"],
        })


def run_options_web(tickers: list[str] | None = None, interval: float = 600.0,
                    host: str = "127.0.0.1", port: int = 8001):
    thread = threading.Thread(target=scan_loop, args=(tickers, interval), daemon=True)
    thread.start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    run_options_web(port=port)
