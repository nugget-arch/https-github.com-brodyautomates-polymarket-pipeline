"""First-boot bootstrap: create the single admin user if none exists."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.security import hash_password
from ..domain.enums import Role
from ..domain.models import User
from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("bootstrap")


async def ensure_admin_user(session: AsyncSession) -> None:
    existing = await session.execute(select(User.id))
    if existing.scalars().first() is not None:
        return
    s = get_settings()
    user = User(
        email=s.bootstrap_admin_email,
        password_hash=hash_password(s.bootstrap_admin_password),
        role=Role.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    log.info("bootstrap_admin_created", email=s.bootstrap_admin_email)
