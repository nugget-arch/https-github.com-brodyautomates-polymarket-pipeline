"""Test fixtures: in-memory sqlite, app with lifespan, HTTP client."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-deterministic")
os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "test-password-123")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def client():
    # Import inside the fixture so env vars above are read first.
    from httpx import ASGITransport, AsyncClient

    from cryptoption_api.db import reset_engine
    from cryptoption_api.main import create_app
    from cryptoption_api.settings import get_settings

    get_settings.cache_clear()
    await reset_engine()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
    await reset_engine()
