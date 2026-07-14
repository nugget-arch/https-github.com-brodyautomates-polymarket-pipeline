"""Trading session lifecycle + trade history REST."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import current_user, require_csrf
from ..db import get_session
from ..domain.enums import ExecutionMode, SessionStatus
from ..domain.models import PaperOrder, Settlement, TradingSession, User
from ..runtime.session import run_paper_session

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


class StartSessionRequest(BaseModel):
    asset: str = "BTCUSDT"
    mode: ExecutionMode = ExecutionMode.PAPER
    n_candles: int = 400
    seed: int = 7
    model: str = "trend"
    payout: float = 0.80
    expiry_bars: int = 1


@router.post("/run")
async def run_session(
    body: StartSessionRequest, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session), _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    """Run a deterministic PAPER or SHADOW session over synthetic data and
    return a summary. MANUAL and OFFICIAL are not run here (MANUAL is the
    interactive /manual flow; OFFICIAL execution is disabled)."""
    if body.mode not in (ExecutionMode.PAPER, ExecutionMode.SHADOW):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "only PAPER or SHADOW sessions can be run here")
    return await run_paper_session(
        session, user.id, body.asset, body.mode, n_candles=body.n_candles,
        seed=body.seed, model_name=body.model, payout=body.payout,
        expiry_bars=body.expiry_bars)


@router.post("/{session_id}/kill-switch")
async def kill_switch(
    session_id: int, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session), _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    ts = await session.get(TradingSession, session_id)
    if ts is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    ts.kill_switch = True
    ts.status = SessionStatus.HALTED
    await session.commit()
    return {"status": "halted", "session_id": str(session_id)}


@router.get("/trades/history")
async def trade_history(
    limit: int = 100, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (await session.execute(
        select(PaperOrder, Settlement)
        .join(Settlement, Settlement.order_id == PaperOrder.id, isouter=True)
        .order_by(PaperOrder.id.desc()).limit(limit))).all()
    out: list[dict[str, Any]] = []
    for order, settle in rows:
        out.append({
            "id": order.id, "session_id": order.session_id, "action": order.action.value,
            "stake": order.stake, "payout": order.payout, "entry_price": order.entry_price,
            "state": order.state.value, "data_source": order.data_source,
            "pnl": settle.pnl if settle else None,
            "exit_price": settle.exit_price if settle else None,
        })
    return out
