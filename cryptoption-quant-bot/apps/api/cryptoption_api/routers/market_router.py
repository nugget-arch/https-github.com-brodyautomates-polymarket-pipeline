"""Market REST: asset list, recent candles (WS state recovery), data-quality."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import current_user
from ..db import get_session
from ..domain.models import Asset, User
from ..runtime.market_feed import get_feed_manager

router = APIRouter(prefix="/api/v1/market", tags=["market"])


class AssetOut(BaseModel):
    id: int
    symbol: str
    market_type: str
    is_otc: bool


@router.get("/assets", response_model=list[AssetOut])
async def list_assets(
    _user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[AssetOut]:
    rows = (await session.execute(select(Asset).order_by(Asset.symbol))).scalars().all()
    return [
        AssetOut(id=a.id, symbol=a.symbol, market_type=a.market_type.value, is_otc=a.is_otc)
        for a in rows
    ]


@router.get("/candles")
async def recent_candles(
    asset: str = Query(default="BTCUSDT"),
    limit: int = Query(default=120, ge=1, le=240),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Recent CLOSED candles for the asset's live feed — used by the frontend
    to recover chart state on (re)connect. Ensures the feed is running."""
    from ..settings import get_settings

    feed = await get_feed_manager().ensure(
        asset, bar_seconds=60, speed=get_settings().feed_speed_seconds
    )
    return {"asset": asset, "candles": feed.recent_candles(limit=limit),
            "last_price": feed.last_price}
