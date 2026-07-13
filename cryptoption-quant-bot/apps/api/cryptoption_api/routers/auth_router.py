"""Auth routes: login, logout, me. Single-user oriented, roles enforced."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    current_user,
    get_tokens,
    rate_limit,
    require_csrf,
)
from ..auth.security import verify_password
from ..db import get_session
from ..domain.models import User
from ..schemas.dto import LoginRequest, UserOut
from ..settings import get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_auth_cookies(response: Response, user_id: int) -> None:
    tokens = get_tokens()
    secure = get_settings().app_env == "production"
    response.set_cookie(
        SESSION_COOKIE,
        tokens.issue(user_id),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    # CSRF cookie is readable by JS (double-submit pattern), not httponly.
    response.set_cookie(
        CSRF_COOKIE,
        tokens.issue_csrf(),
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit),
) -> UserOut:
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    _set_auth_cookies(response, user.id)
    return UserOut(id=user.id, email=user.email, role=user.role)


@router.post("/logout")
async def logout(response: Response, _csrf: None = Depends(require_csrf)) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, role=user.role)
