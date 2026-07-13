"""SQLAlchemy 2 ORM models for the domain entities.

Types are kept cross-database (Postgres in prod, sqlite in tests): only
String/Integer/Float/Boolean/DateTime(tz)/JSON/Enum are used. Every decision
row carries dataset/feature/model/config-hash + seed so any record is
reproducible from scratch. All market/PnL data is append-only; corrections are
new compensating events, never in-place edits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .enums import (
    Action,
    ExecutionMode,
    ManualResult,
    MarketType,
    NoTradeReason,
    OrderState,
    Role,
    SessionStatus,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    market_type: Mapped[MarketType] = mapped_column(Enum(MarketType))
    is_otc: Mapped[bool] = mapped_column(Boolean, default=False)
    tick_size: Mapped[float] = mapped_column(Float, default=0.0)
    __table_args__ = (UniqueConstraint("symbol", "market_type", name="uq_asset_symbol_market"),)


class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(32))
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("asset_id", "ts_utc", "source", name="uq_candle"),)


class PayoutSnapshot(Base):
    __tablename__ = "payout_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expiry_seconds: Mapped[int] = mapped_column(Integer)
    payout: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64))  # manual/import only


class _Version(Base, TimestampMixin):
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(64))
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    code_hash: Mapped[str] = mapped_column(String(64), default="")
    config_hash: Mapped[str] = mapped_column(String(64), default="")


class DatasetVersion(_Version):
    __tablename__ = "dataset_versions"


class StrategyVersion(_Version):
    __tablename__ = "strategy_versions"


class ModelVersion(_Version):
    __tablename__ = "model_versions"


class TradingSession(Base, TimestampMixin):
    __tablename__ = "trading_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    mode: Mapped[ExecutionMode] = mapped_column(Enum(ExecutionMode))
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.ACTIVE)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    orders: Mapped[list[PaperOrder]] = relationship(back_populates="session")


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("trading_sessions.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    p_up: Mapped[float] = mapped_column(Float)
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id"), nullable=True
    )
    feature_vector_hash: Mapped[str] = mapped_column(String(64), default="")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    action: Mapped[Action] = mapped_column(Enum(Action))
    threshold_call: Mapped[float] = mapped_column(Float)
    threshold_put: Mapped[float] = mapped_column(Float)


class RiskDecision(Base):
    __tablename__ = "risk_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
    stake: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(64), default="ok")
    no_trade_reason: Mapped[NoTradeReason | None] = mapped_column(
        Enum(NoTradeReason), nullable=True
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("trading_sessions.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    action: Mapped[Action] = mapped_column(Enum(Action))
    stake: Mapped[float] = mapped_column(Float)
    payout: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[OrderState] = mapped_column(Enum(OrderState), default=OrderState.CREATED)
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_versions.id"), nullable=True
    )
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id"), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[TradingSession] = relationship(back_populates="orders")


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), index=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[OrderState] = mapped_column(Enum(OrderState))
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    settled_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExternalManualTrade(Base):
    __tablename__ = "external_manual_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[ManualResult | None] = mapped_column(Enum(ManualResult), nullable=True)
    theoretical_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("trading_sessions.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    balance: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)


class AuditEvent(Base):
    """Immutable hash-chained journal. Never edited; corrections are new events."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    kind: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis: Mapped[str] = mapped_column(String(1024))
    primary_metric: Mapped[str] = mapped_column(String(64))
    rejection_criterion: Mapped[str] = mapped_column(String(512))
    seed: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64), default="")
    verdict: Mapped[str] = mapped_column(String(128), default="")
