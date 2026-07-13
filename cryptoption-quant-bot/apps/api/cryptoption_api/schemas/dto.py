"""Pydantic DTOs for request/response bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from ..domain.enums import Action, ExecutionMode, NoTradeReason, Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    role: Role


class HealthOut(BaseModel):
    status: str
    version: str
    execution_enabled: bool


class ReadyOut(BaseModel):
    status: str
    database: str
    redis: str


class DashboardState(BaseModel):
    """Static snapshot the dashboard renders; real-time deltas arrive via WS.
    Phase 1 serves mock but well-typed values so the UI contract is fixed."""

    bot_status: str
    mode: ExecutionMode
    balance: float
    pnl_day: float
    pnl_total: float
    win_rate: float | None
    break_even: float
    edge: float | None
    expected_value: float | None
    drawdown: float
    consecutive_losses: int
    n_trades: int
    data_status: str
    model_status: str
    kill_switch: bool
    asset: str
    price: float | None
    payout: float
    p_up: float | None
    threshold_call: float
    threshold_put: float
    current_action: Action
    no_trade_reason: NoTradeReason | None
    proposed_stake: float
    countdown_seconds: int | None


class TradeRow(BaseModel):
    id: int
    ts: datetime
    asset: str
    action: Action
    entry: float | None
    exit: float | None
    expiry: datetime | None
    stake: float
    payout: float
    probability: float | None
    threshold: float
    result: str
    pnl: float
    account: ExecutionMode
    strategy: str
    model: str
    latency_ms: int | None
    data_source: str
