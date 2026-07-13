"""Typed application settings (Pydantic Settings), sourced from env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "dev-insecure-secret-change-me"

    # Postgres in prod; tests override with an in-memory sqlite URL.
    database_url: str = "postgresql+asyncpg://cqb:cqb@localhost:5432/cqb"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: str = "http://localhost:3000"

    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "change-me-please"
    session_ttl_minutes: int = 720
    rate_limit_per_minute: int = 120

    # Synthetic market-feed pacing (seconds per tick). 1.0 ≈ real time; tests
    # override with a small value for speed.
    feed_speed_seconds: float = 1.0

    # Mirrors quant_engine.EXECUTION_ENABLED. Real-money execution is disabled
    # in code regardless of this flag; it exists only to make the intent auditable.
    execution_enabled: bool = Field(default=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
