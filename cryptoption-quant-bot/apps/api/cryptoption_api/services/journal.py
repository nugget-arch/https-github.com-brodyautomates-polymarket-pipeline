"""Immutable, hash-chained journal persisted in Postgres.

Every record stores the hash of the previous one, so any deletion or edit
breaks the chain and `verify()` returns False. Closed records are never edited
in place — a correction is appended as a new compensating event.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import AuditEvent

_GENESIS = "0" * 64


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so datetimes etc. become storable strings and the
    stored payload matches exactly what was hashed."""
    safe: dict[str, Any] = json.loads(json.dumps(payload, sort_keys=True, default=str))
    return safe


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _hash(prev_hash: str, seq: int, kind: str, payload: dict[str, Any]) -> str:
    material = prev_hash + _canonical({"seq": seq, "kind": kind, "payload": payload})
    return hashlib.sha256(material.encode()).hexdigest()


class JournalService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _tail(self) -> tuple[int, str]:
        row = (
            await self.session.execute(
                select(AuditEvent.seq, AuditEvent.hash)
                .order_by(AuditEvent.seq.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return 0, _GENESIS
        return int(row[0]) + 1, str(row[1])

    async def append(self, kind: str, payload: dict[str, Any]) -> AuditEvent:
        seq, prev_hash = await self._tail()
        payload = _json_safe(payload)  # store exactly what we hash
        digest = _hash(prev_hash, seq, kind, payload)
        event = AuditEvent(seq=seq, kind=kind, payload_json=payload,
                           prev_hash=prev_hash, hash=digest)
        self.session.add(event)
        await self.session.commit()
        return event

    async def verify(self) -> bool:
        rows = (
            await self.session.execute(
                select(AuditEvent).order_by(AuditEvent.seq.asc())
            )
        ).scalars().all()
        prev = _GENESIS
        expected_seq = 0
        for ev in rows:
            if ev.seq != expected_seq or ev.prev_hash != prev:
                return False
            if _hash(ev.prev_hash, ev.seq, ev.kind, ev.payload_json) != ev.hash:
                return False
            prev = ev.hash
            expected_seq += 1
        return True

    async def count(self) -> int:
        return int((await self.session.execute(select(func.count(AuditEvent.id)))).scalar_one())
