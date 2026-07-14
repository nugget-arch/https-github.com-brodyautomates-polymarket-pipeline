"""Manual-confirmation flow.

The bot produces a signal; the human opens the trade THEMSELVES on their own
platform and reports back. We never send an order anywhere. When the user
reports the outcome we also compute the price-implied ("theoretical") outcome
from entry/exit and compare — a disagreement flags a broker whose payout didn't
match the actual price move.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import current_user, require_csrf
from ..db import get_session
from ..domain.enums import Action, ExecutionMode, ManualResult, SessionStatus
from ..domain.models import (
    Asset,
    ExternalManualTrade,
    Prediction,
    Signal,
    TradingSession,
    User,
)
from ..services.journal import JournalService

router = APIRouter(prefix="/api/v1/manual", tags=["manual"])


class ConfirmRequest(BaseModel):
    asset: str = "EURUSD_OTC"
    action: Action = Action.CALL
    p_up: float = Field(0.6, ge=0.0, le=1.0)
    entry_price: float
    payout: float = 0.80
    stake: float = 0.0
    external_id: str | None = None


class ResultRequest(BaseModel):
    result: ManualResult
    exit_price: float | None = None


async def _manual_session(session: AsyncSession, user_id: int, asset_id: int) -> TradingSession:
    ts = (
        (
            await session.execute(
                select(TradingSession).where(
                    TradingSession.user_id == user_id,
                    TradingSession.mode == ExecutionMode.MANUAL,
                    TradingSession.status == SessionStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .first()
    )
    if ts is None:
        ts = TradingSession(
            user_id=user_id,
            asset_id=asset_id,
            mode=ExecutionMode.MANUAL,
            status=SessionStatus.ACTIVE,
        )
        session.add(ts)
        await session.commit()
    return ts


@router.post("/confirm")
async def confirm(
    body: ConfirmRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    if body.action == Action.NO_TRADE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot confirm a NO_TRADE")
    asset = (
        await session.execute(select(Asset).where(Asset.symbol == body.asset))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found")

    ts = await _manual_session(session, user.id, asset.id)
    pred = Prediction(session_id=ts.id, p_up=body.p_up)
    session.add(pred)
    await session.commit()
    sig = Signal(prediction_id=pred.id, action=body.action, threshold_call=0.0, threshold_put=0.0)
    session.add(sig)
    await session.commit()
    trade = ExternalManualTrade(
        signal_id=sig.id,
        external_id=body.external_id,
        entry_ts=datetime.now(UTC),
        entry_price=body.entry_price,
        payout=body.payout,
    )
    session.add(trade)
    await session.commit()

    await JournalService(session).append(
        "manual_confirm",
        {
            "trade_id": trade.id,
            "asset": body.asset,
            "action": body.action.value,
            "entry_price": body.entry_price,
            "payout": body.payout,
            "external_id": body.external_id,
        },
    )
    return {"trade_id": trade.id, "signal_id": sig.id, "status": "PENDING_CONFIRMATION"}


def _theoretical(action: Action, entry: float, exit_price: float) -> str:
    if exit_price == entry:
        return "TIED"
    up = exit_price > entry
    return "WON" if ((action == Action.CALL) == up) else "LOST"


@router.post("/{trade_id}/result")
async def report_result(
    trade_id: int,
    body: ResultRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    trade = await session.get(ExternalManualTrade, trade_id)
    if trade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trade not found")
    sig = await session.get(Signal, trade.signal_id)
    trade.result = body.result
    theoretical: str | None = None
    agrees: bool | None = None
    if body.exit_price is not None and trade.entry_price is not None and sig is not None:
        theoretical = _theoretical(sig.action, trade.entry_price, body.exit_price)
        trade.theoretical_result = theoretical
        agrees = body.result.value == theoretical
    await session.commit()

    await JournalService(session).append(
        "manual_result",
        {
            "trade_id": trade_id,
            "external_result": body.result.value,
            "exit_price": body.exit_price,
            "theoretical_result": theoretical,
            "external_matches_theoretical": agrees,
        },
    )
    return {
        "trade_id": trade_id,
        "external_result": body.result.value,
        "theoretical_result": theoretical,
        "external_matches_theoretical": agrees,
    }
