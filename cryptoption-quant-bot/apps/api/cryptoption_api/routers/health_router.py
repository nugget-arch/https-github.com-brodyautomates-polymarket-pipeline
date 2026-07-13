"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from .. import __version__
from ..db import get_engine
from ..schemas.dto import HealthOut, ReadyOut
from ..settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(
        status="ok",
        version=__version__,
        execution_enabled=get_settings().execution_enabled,
    )


@router.get("/ready", response_model=ReadyOut)
async def ready() -> ReadyOut:
    db_ok = "ok"
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = "unavailable"
    # Redis is probed lazily; Phase 1 reports "unknown" without a live client.
    return ReadyOut(status="ok" if db_ok == "ok" else "degraded", database=db_ok, redis="unknown")
