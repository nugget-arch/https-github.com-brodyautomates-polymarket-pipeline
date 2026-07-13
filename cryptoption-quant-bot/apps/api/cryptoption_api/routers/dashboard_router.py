"""Dashboard state (Phase 1: typed mock, auth-protected).

Serves a well-typed snapshot so the frontend contract is frozen now. Real-time
deltas will arrive over WebSocket in later phases; the numbers here are
placeholders and are NOT evidence of any edge.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from quant_engine import break_even_win_rate

from ..auth.dependencies import current_user
from ..domain.enums import Action, ExecutionMode
from ..domain.models import User
from ..schemas.dto import DashboardState

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/state", response_model=DashboardState)
async def dashboard_state(_user: User = Depends(current_user)) -> DashboardState:
    payout = 0.80
    return DashboardState(
        bot_status="idle",
        mode=ExecutionMode.PAPER,
        balance=10_000.0,
        pnl_day=0.0,
        pnl_total=0.0,
        win_rate=None,
        break_even=break_even_win_rate(payout),
        edge=None,
        expected_value=None,
        drawdown=0.0,
        consecutive_losses=0,
        n_trades=0,
        data_status="disconnected",
        model_status="not_loaded",
        kill_switch=False,
        asset="BTCUSDT",
        price=None,
        payout=payout,
        p_up=None,
        threshold_call=break_even_win_rate(payout) + 0.02,
        threshold_put=1.0 - (break_even_win_rate(payout) + 0.02),
        current_action=Action.NO_TRADE,
        no_trade_reason=None,
        proposed_stake=0.0,
        countdown_seconds=None,
    )
