"""SQLite experiment registry: every run is recorded with config + seed so any
result can be reproduced from scratch."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    verdict TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    strategy TEXT NOT NULL,
    expiry_bars INTEGER NOT NULL,
    metrics_json TEXT NOT NULL
);
"""


class ExperimentRegistry:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record(
        self,
        seed: int,
        config: dict[str, Any],
        verdict: str,
        summary: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> int:
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO experiments (created_utc, seed, config_json, verdict, summary_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    seed,
                    json.dumps(config, default=str),
                    verdict,
                    json.dumps(summary, default=str),
                ),
            )
            exp_id = int(cur.lastrowid)
            for r in results:
                con.execute(
                    "INSERT INTO results (experiment_id, strategy, expiry_bars, metrics_json) "
                    "VALUES (?, ?, ?, ?)",
                    (exp_id, r["strategy"], r["expiry_bars"],
                     json.dumps(r["metrics"], default=str)),
                )
        return exp_id

    def list_experiments(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, created_utc, seed, verdict FROM experiments "
                "ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [
            {"id": r[0], "created_utc": r[1], "seed": r[2], "verdict": r[3]}
            for r in rows
        ]
