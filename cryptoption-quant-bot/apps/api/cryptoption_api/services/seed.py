"""Seed a small set of assets (idempotent). Keeps market types separate."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import MarketType
from ..domain.models import Asset

_SEED = [
    ("BTCUSDT", MarketType.CRYPTO_BINANCE, False),
    ("ETHUSDT", MarketType.CRYPTO_BINANCE, False),
    ("EURUSD_OTC", MarketType.FOREX_OTC, True),
]


async def ensure_assets(session: AsyncSession) -> None:
    existing = {
        s for s in (await session.execute(select(Asset.symbol))).scalars().all()
    }
    added = False
    for symbol, market_type, is_otc in _SEED:
        if symbol not in existing:
            session.add(Asset(symbol=symbol, market_type=market_type, is_otc=is_otc))
            added = True
    if added:
        await session.commit()
