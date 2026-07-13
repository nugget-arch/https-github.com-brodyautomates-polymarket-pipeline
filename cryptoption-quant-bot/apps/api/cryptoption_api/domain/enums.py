"""Domain enums shared across API, persistence and (later) the quant engine."""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class MarketType(enum.StrEnum):
    CRYPTO_BINANCE = "CRYPTO_BINANCE"
    FOREX_OTC = "FOREX_OTC"
    NORMAL = "NORMAL"
    SYNTHETIC = "SYNTHETIC"


class ExecutionMode(enum.StrEnum):
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    MANUAL = "MANUAL"
    OFFICIAL_DISABLED = "OFFICIAL_DISABLED"


class Action(enum.StrEnum):
    CALL = "CALL"
    PUT = "PUT"
    NO_TRADE = "NO_TRADE"


class NoTradeReason(enum.StrEnum):
    PROBABILITY_TOO_LOW = "PROBABILITY_TOO_LOW"
    PAYOUT_TOO_LOW = "PAYOUT_TOO_LOW"
    UNCERTAINTY_TOO_HIGH = "UNCERTAINTY_TOO_HIGH"
    LATENCY_TOO_HIGH = "LATENCY_TOO_HIGH"
    RISK_LIMIT = "RISK_LIMIT"
    ACTIVE_POSITION_EXISTS = "ACTIVE_POSITION_EXISTS"
    SESSION_HALTED = "SESSION_HALTED"
    DATA_QUALITY = "DATA_QUALITY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_DEGRADED = "MODEL_DEGRADED"
    MARKET_REGIME_UNSUPPORTED = "MARKET_REGIME_UNSUPPORTED"
    KILL_SWITCH = "KILL_SWITCH"
    COOLDOWN = "COOLDOWN"


class OrderState(enum.StrEnum):
    CREATED = "CREATED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    TIED = "TIED"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"
    EXPIRED_WITHOUT_DATA = "EXPIRED_WITHOUT_DATA"


class SessionStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    ENDED = "ENDED"


class TiePolicy(enum.StrEnum):
    LOSS = "LOSS"
    TIE = "TIE"
    EXCLUDE = "EXCLUDE"


class ManualResult(enum.StrEnum):
    WON = "WON"
    LOST = "LOST"
    TIED = "TIED"
    SOLD = "SOLD"
    REJECTED = "REJECTED"
