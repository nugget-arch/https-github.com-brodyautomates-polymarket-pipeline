"""Immutable journal: hash chain detects tampering and holes."""
from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest_asyncio


@pytest_asyncio.fixture
async def db_session():
    from cryptoption_api.db import Base, get_engine, get_sessionmaker, reset_engine
    from cryptoption_api.settings import get_settings

    get_settings.cache_clear()
    await reset_engine()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as s:
        yield s
    await reset_engine()


async def test_journal_appends_and_verifies(db_session):
    from cryptoption_api.services.journal import JournalService

    j = JournalService(db_session)
    await j.append("signal", {"p_up": 0.61})
    await j.append("decision", {"action": "shadow"})
    await j.append("settlement", {"outcome": "loss", "pnl": -1.0})
    assert await j.count() == 3
    assert await j.verify() is True


async def test_journal_detects_tampering(db_session):
    from sqlalchemy import select

    from cryptoption_api.domain.models import AuditEvent
    from cryptoption_api.services.journal import JournalService

    j = JournalService(db_session)
    await j.append("signal", {"p_up": 0.61})
    await j.append("settlement", {"outcome": "loss", "pnl": -1.0})
    assert await j.verify()

    # tamper: flip a recorded outcome from loss to win
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.seq == 1))).scalar_one()
    ev.payload_json = {"outcome": "win", "pnl": 1.0}
    await db_session.commit()
    assert await j.verify() is False


async def test_journal_detects_deleted_record(db_session):
    from sqlalchemy import delete

    from cryptoption_api.domain.models import AuditEvent
    from cryptoption_api.services.journal import JournalService

    j = JournalService(db_session)
    for i in range(4):
        await j.append("x", {"i": i})
    await db_session.execute(delete(AuditEvent).where(AuditEvent.seq == 2))
    await db_session.commit()
    assert await j.verify() is False  # hole in the chain
