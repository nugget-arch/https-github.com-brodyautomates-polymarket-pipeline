"""Paper/shadow session driver.

Runs a TradingRuntime over a deterministic synthetic candle series, persists
orders/settlements, appends every event to the immutable journal, publishes WS
events, and returns a summary. Deterministic given (asset, seed, n_candles),
which keeps sessions reproducible and testable. A future always-on variant can
reuse the same TradingRuntime driven by the live market feed.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quant_engine.backtest.engine import decision_threshold
from quant_engine.config import BacktestConfig, RiskConfig
from quant_engine.strategies import make_model

from ..domain.enums import Action, ExecutionMode, OrderState, SessionStatus
from ..domain.models import Asset, PaperOrder, Settlement, TradingSession
from ..services.journal import JournalService
from ..ws.bus import EventBus, get_bus
from .market_feed import tick_channel
from .trading import TradingRuntime


def generate_candles(
    asset: str,
    n: int,
    *,
    seed: int = 7,
    bar_seconds: int = 60,
    start_price: float = 100.0,
    base_vol: float = 8e-4,
) -> list[dict[str, Any]]:
    """Deterministic OHLC candles (seeded random walk with vol clustering)."""
    rng = random.Random(seed)
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    price, vol, prev = start_price, base_vol, 0.0
    out: list[dict[str, Any]] = []
    for _ in range(n):
        vol = 0.94 * vol + 0.06 * abs(prev)
        ret = rng.gauss(0, max(vol, base_vol * 0.25))
        prev = ret
        o = price
        c = max(0.01, o * (1 + ret))
        hi = max(o, c) * (1 + abs(rng.gauss(0, base_vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, base_vol / 2)))
        out.append(
            {
                "ts_utc": ts,
                "asset": asset,
                "open": o,
                "high": hi,
                "low": lo,
                "close": c,
                "volume": rng.uniform(1, 10),
                "session_id": ts.strftime("%Y-%m-%d"),
                "is_otc": False,
            }
        )
        price = c
        ts += timedelta(seconds=bar_seconds)
    return out


async def run_paper_session(
    session: AsyncSession,
    user_id: int,
    asset_symbol: str,
    mode: ExecutionMode,
    *,
    n_candles: int = 400,
    seed: int = 7,
    model_name: str = "trend",
    payout: float = 0.80,
    expiry_bars: int = 1,
    bus: EventBus | None = None,
) -> dict[str, Any]:
    if mode not in (ExecutionMode.PAPER, ExecutionMode.SHADOW):
        raise ValueError("run_paper_session supports PAPER or SHADOW only")
    bus = bus or get_bus()
    journal = JournalService(session)

    asset = (await session.execute(select(Asset).where(Asset.symbol == asset_symbol))).scalar_one()
    ts_row = TradingSession(
        user_id=user_id, asset_id=asset.id, mode=mode, status=SessionStatus.ACTIVE
    )
    session.add(ts_row)
    await session.commit()

    bt = BacktestConfig(payout_base=payout)
    threshold = decision_threshold(bt)
    model = make_model(model_name, seed=seed)
    runtime = TradingRuntime(
        mode=mode.value,
        predict_fn=lambda row: float(model.predict_proba(row)[0]),
        threshold=threshold,
        payout=payout,
        expiry_bars=expiry_bars,
        risk_cfg=RiskConfig(),
    )

    await journal.append(
        "session_start",
        {
            "session_id": ts_row.id,
            "mode": mode.value,
            "asset": asset_symbol,
            "threshold": threshold,
            "break_even": runtime.break_even,
            "seed": seed,
        },
    )

    for candle in generate_candles(asset_symbol, n_candles, seed=seed):
        for ev in runtime.on_closed_candle(candle):
            await journal.append(ev.type, {"session_id": ts_row.id, **ev.payload})
            await bus.publish(
                tick_channel(asset_symbol), {"type": f"trade.{ev.type}", "payload": ev.payload}
            )
            if ev.type == "order_opened" and mode == ExecutionMode.PAPER:
                order = PaperOrder(
                    session_id=ts_row.id,
                    asset_id=asset.id,
                    action=Action(ev.payload["action"]),
                    stake=ev.payload["stake"],
                    payout=ev.payload["payout"],
                    entry_price=ev.payload["entry_price"],
                    state=OrderState.OPEN,
                    data_source="synthetic",
                )
                session.add(order)
                await session.commit()
            elif ev.type == "settlement" and mode == ExecutionMode.PAPER:
                last = (
                    await session.execute(
                        select(PaperOrder)
                        .where(
                            PaperOrder.session_id == ts_row.id, PaperOrder.state == OrderState.OPEN
                        )
                        .order_by(PaperOrder.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                result_map = {
                    "win": OrderState.WON,
                    "loss": OrderState.LOST,
                    "tie": OrderState.TIED,
                }
                if last is not None:
                    last.state = result_map[ev.payload["outcome"]]
                    session.add(
                        Settlement(
                            order_id=last.id,
                            exit_price=ev.payload["exit_price"],
                            result=last.state,
                            pnl=ev.payload["pnl"],
                        )
                    )
                    await session.commit()

    ts_row.status = SessionStatus.ENDED
    ts_row.ended_at = datetime.now(UTC)
    await session.commit()
    summary = {
        "session_id": ts_row.id,
        "mode": mode.value,
        "signals": runtime.n_signals,
        "settled_trades": runtime.n_trades,
        "wins": runtime.n_wins,
        "win_rate": (runtime.n_wins / runtime.n_trades) if runtime.n_trades else None,
        "final_balance": round(runtime.balance, 2) if mode == ExecutionMode.PAPER else None,
        "break_even": runtime.break_even,
        "journal_ok": await journal.verify(),
    }
    await journal.append("session_end", {**summary})
    return summary
