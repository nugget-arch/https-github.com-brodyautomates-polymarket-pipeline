#!/usr/bin/env python3
"""
Options analyzer — verified track record.

Every scan's top picks are persisted; once their expiries pass, each pick is
verified against the real settlement price (Yahoo daily closes) and the
realized P/L is compared with what the model promised. This is how the tool
earns (or loses) trust: predicted POP vs realized win rate, predicted EV vs
realized P/L, in the open.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

DB_PATH = Path(__file__).parent / "options_history.db"
_UA = {"User-Agent": "Mozilla/5.0"}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT NOT NULL,
            total_strategies INTEGER
        );
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER REFERENCES scans(id),
            ticker TEXT, name TEXT, family TEXT, expiry TEXT,
            dte REAL, spot REAL, legs TEXT,           -- JSON payoff_legs
            pop_exec REAL, ev_exec REAL, capital REAL, slippage REAL,
            verified INTEGER DEFAULT 0,
            terminal_price REAL, realized_pl REAL, won INTEGER,
            UNIQUE(scan_id, ticker, name, expiry)
        );
    """)
    return conn


def record_scan(result: dict) -> None:
    """Persist a scan's top picks for later verification."""
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO scans (generated_at, total_strategies) VALUES (?, ?)",
        (result["generated_at"], result["total_strategies"]),
    )
    scan_id = cur.lastrowid
    for r in result.get("top_picks", []):
        conn.execute(
            """INSERT OR IGNORE INTO picks
               (scan_id, ticker, name, family, expiry, dte, spot, legs,
                pop_exec, ev_exec, capital, slippage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scan_id, r["ticker"], r["name"], r["family"], r["expiry"],
             r["dte"], r["spot"], json.dumps(r["payoff_legs"]),
             r["pop_exec"], r["ev_exec"], r["capital"], r["slippage"]),
        )
    conn.commit()
    conn.close()


def _fetch_close_on(ticker: str, date: str) -> float | None:
    """Daily close on (or last close before) `date`, from Yahoo chart API."""
    try:
        resp = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": "1d", "range": "6mo"},
            headers=_UA, timeout=15,
        )
        resp.raise_for_status()
        r = resp.json()["chart"]["result"][0]
        stamps = r["timestamp"]
        closes = r["indicators"]["quote"][0]["close"]
        target = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        best = None
        for ts, c in zip(stamps, closes):
            if c is not None and ts <= target + 86400:
                best = c
        return float(best) if best is not None else None
    except Exception:
        return None


def _realized_pl(row: sqlite3.Row, terminal: float) -> float:
    """Exact P/L at settlement, at executable entry (slippage included)."""
    pl = 0.0
    for leg in json.loads(row["legs"]):
        intrinsic = (max(terminal - leg["strike"], 0.0) if leg["kind"] == "C"
                     else max(leg["strike"] - terminal, 0.0))
        pl += leg["qty"] * (intrinsic - leg["mid"])
    if row["family"] == "covered_call":
        pl += terminal - row["spot"]
    return pl * 100 - row["slippage"]


def verify_expired() -> int:
    """Verify all unverified picks whose expiry has passed. Returns count."""
    conn = _conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM picks WHERE verified = 0 AND expiry < ?", (today,)
    ).fetchall()
    done = 0
    closes: dict[tuple, float | None] = {}
    for row in rows:
        key = (row["ticker"], row["expiry"])
        if key not in closes:
            closes[key] = _fetch_close_on(row["ticker"], row["expiry"])
        terminal = closes[key]
        if terminal is None:
            continue
        pl = _realized_pl(row, terminal)
        conn.execute(
            "UPDATE picks SET verified=1, terminal_price=?, realized_pl=?, won=? WHERE id=?",
            (round(terminal, 2), round(pl, 2), 1 if pl > 0 else 0, row["id"]),
        )
        done += 1
    conn.commit()
    conn.close()
    return done


def get_track_record() -> dict:
    """Aggregate verified performance: model promises vs reality."""
    conn = _conn()
    total_tracked = conn.execute("SELECT COUNT(*) c FROM picks").fetchone()["c"]
    v = conn.execute("""
        SELECT COUNT(*) n, AVG(pop_exec) pred_pop, AVG(won) real_win,
               SUM(ev_exec) pred_ev, SUM(realized_pl) real_pl
        FROM picks WHERE verified = 1
    """).fetchone()
    buckets = conn.execute("""
        SELECT CAST(pop_exec * 10 AS INT) decile, COUNT(*) n,
               AVG(pop_exec) pred, AVG(won) real
        FROM picks WHERE verified = 1 GROUP BY decile ORDER BY decile
    """).fetchall()
    pending = conn.execute(
        "SELECT COUNT(*) c FROM picks WHERE verified = 0").fetchone()["c"]
    conn.close()
    return {
        "tracked": total_tracked,
        "pending": pending,
        "verified": v["n"] or 0,
        "predicted_pop": round(v["pred_pop"] or 0, 4),
        "realized_winrate": round(v["real_win"] or 0, 4),
        "predicted_ev": round(v["pred_ev"] or 0, 2),
        "realized_pl": round(v["real_pl"] or 0, 2),
        "calibration": [
            {"decile": b["decile"], "n": b["n"],
             "predicted": round(b["pred"], 3), "realized": round(b["real"], 3)}
            for b in buckets
        ],
    }
