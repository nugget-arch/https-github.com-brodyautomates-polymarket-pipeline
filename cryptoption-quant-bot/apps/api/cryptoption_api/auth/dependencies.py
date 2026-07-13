"""Auth dependencies: current user, role guard, CSRF, in-memory rate limiter."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain.enums import Role
from ..domain.models import User
from ..settings import get_settings
from .security import SessionTokens

SESSION_COOKIE = "cqb_session"
CSRF_COOKIE = "cqb_csrf"
CSRF_HEADER = "x-csrf-token"


def get_tokens() -> SessionTokens:
    s = get_settings()
    return SessionTokens(s.secret_key, s.session_ttl_minutes)


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    uid = get_tokens().read(token) if token else None
    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user = await session.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")
    return user


def require_role(role: Role) -> Callable[..., Awaitable[User]]:
    async def guard(user: User = Depends(current_user)) -> User:
        if user.role != role and user.role != Role.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return guard


def require_csrf(request: Request) -> None:
    """Enforce double-submit CSRF on unsafe methods."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or header != cookie or not get_tokens().check_csrf(header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf validation failed")


_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(request: Request) -> None:
    limit = get_settings().rate_limit_per_minute
    key = request.client.host if request.client else "anon"
    now = time.monotonic()
    window = [t for t in _hits[key] if now - t < 60]
    if len(window) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
    window.append(now)
    _hits[key] = window


async def get_user_count(session: AsyncSession) -> int:
    result = await session.execute(select(User.id))
    return len(result.scalars().all())
