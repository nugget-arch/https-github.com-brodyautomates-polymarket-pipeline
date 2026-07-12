"""Immutable append-only journal with a SHA-256 hash chain.

Every signal, probability, decision and outcome is appended as one JSON line
carrying the hash of the previous record. `verify()` detects any tampering or
deletion — the paper track record cannot be quietly edited after the fact.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

_GENESIS = "0" * 64


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq, self._prev_hash = self._tail()

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0, _GENESIS
        last = self.path.read_text().rstrip("\n").rsplit("\n", 1)[-1]
        rec = json.loads(last)
        return int(rec["seq"]) + 1, str(rec["hash"])

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "seq": self._seq,
            "ts": round(time.time(), 3),
            "kind": kind,
            "payload": payload,
            "prev_hash": self._prev_hash,
        }
        record["hash"] = hashlib.sha256(
            (record["prev_hash"] + _canonical({k: v for k, v in record.items() if k != "hash"}))
            .encode()
        ).hexdigest()
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._seq += 1
        self._prev_hash = record["hash"]
        return record

    def verify(self) -> bool:
        """Recompute the whole chain; False on any hole or edit."""
        if not self.path.exists():
            return True
        prev = _GENESIS
        expected_seq = 0
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            if rec["seq"] != expected_seq or rec["prev_hash"] != prev:
                return False
            recomputed = hashlib.sha256(
                (rec["prev_hash"] + _canonical({k: v for k, v in rec.items() if k != "hash"}))
                .encode()
            ).hexdigest()
            if recomputed != rec["hash"]:
                return False
            prev = rec["hash"]
            expected_seq += 1
        return True
