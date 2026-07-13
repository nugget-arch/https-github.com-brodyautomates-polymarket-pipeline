"""Locked final holdout.

The final test segment must be evaluated exactly once, after research is
frozen. Unlocking requires: a frozen config, its hash, and an explicit
confirmation. Every unlock is recorded so the holdout can't be silently reused
to keep optimizing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class HoldoutLockedError(RuntimeError):
    """Raised when the holdout is accessed without a valid unlock."""


@dataclass
class HoldoutLock:
    expected_hash: str
    unlocked: bool = False
    unlock_log: list[dict] = field(default_factory=list)

    def unlock(self, frozen_config: dict[str, Any], confirm: bool) -> None:
        h = config_hash(frozen_config)
        if not confirm:
            raise HoldoutLockedError("explicit confirmation required to unlock the holdout")
        if h != self.expected_hash:
            raise HoldoutLockedError(
                f"config hash mismatch: research was frozen at {self.expected_hash}, "
                f"got {h}. Re-run research; do not tweak config to fit the holdout."
            )
        if self.unlocked:
            raise HoldoutLockedError("holdout already opened once; it must not be reused")
        self.unlocked = True
        self.unlock_log.append({"ts": datetime.now(UTC).isoformat(), "hash": h})

    def require_open(self) -> None:
        if not self.unlocked:
            raise HoldoutLockedError("holdout is locked; freeze research and unlock explicitly")
