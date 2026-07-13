"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .db import Base, get_engine, get_sessionmaker
from .logging_setup import get_logger, setup_logging
from .middleware import SecurityHeadersMiddleware
from .routers import auth_router, dashboard_router, health_router
from .services.bootstrap import ensure_admin_user
from .settings import get_settings

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    # In dev/test create tables directly; production uses Alembic migrations.
    if settings.app_env in ("development", "test"):
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as session:
        await ensure_admin_user(session)
    log.info("api_started", version=__version__, execution_enabled=settings.execution_enabled)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="cryptoption-quant-bot API",
        version=__version__,
        summary="Research/paper/shadow only. No real-money execution.",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(dashboard_router.router)
    return app


app = create_app()
