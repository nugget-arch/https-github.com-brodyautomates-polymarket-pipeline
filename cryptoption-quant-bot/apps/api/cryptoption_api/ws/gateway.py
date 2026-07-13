"""WebSocket gateway.

Client connects to /ws?asset=SYMBOL. The browser only ever talks to us. Flow:
  1. authenticate via the session cookie (same as REST);
  2. send `connection.status`;
  3. ensure the asset's market feed is running;
  4. relay bus messages as sequenced envelopes, interleaving heartbeats.

Sequence IDs let the client detect gaps and recover state via REST. Inbound
messages are limited to {type: "heartbeat"|"ack"} and are otherwise ignored.
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..auth.dependencies import SESSION_COOKIE, get_tokens
from ..logging_setup import get_logger
from ..runtime.market_feed import get_feed_manager, tick_channel
from ..ws.bus import get_bus
from ..ws.events import ConnectionStatusPayload, WsEnvelope

log = get_logger("ws")
router = APIRouter()

HEARTBEAT_SECONDS = 15


async def _authenticate(ws: WebSocket) -> int | None:
    token = ws.cookies.get(SESSION_COOKIE)
    return get_tokens().read(token) if token else None


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, asset: str = Query(default="BTCUSDT")) -> None:
    uid = await _authenticate(ws)
    if uid is None:
        await ws.close(code=4401)  # unauthorized
        return
    await ws.accept()

    seq = 0

    async def send(type_: str, payload: dict[str, object]) -> None:
        nonlocal seq
        env = WsEnvelope.make(seq, type_, payload)  # type: ignore[arg-type]
        seq += 1
        await ws.send_text(env.model_dump_json())

    await send("connection.status",
               ConnectionStatusPayload(state="CONNECTED", asset=asset).model_dump())

    from ..settings import get_settings

    feed = await get_feed_manager().ensure(
        asset, bar_seconds=60, speed=get_settings().feed_speed_seconds
    )
    # replay a little recent history so the chart isn't empty on connect
    for candle in feed.recent_candles(limit=60):
        await send("market.candle", candle)

    bus = get_bus()
    stop = asyncio.Event()

    async def pump_bus() -> None:
        async for msg in bus.subscribe(tick_channel(asset)):
            if stop.is_set():
                return
            await send(msg["type"], msg["payload"])

    async def heartbeat() -> None:
        while not stop.is_set():
            await asyncio.sleep(HEARTBEAT_SECONDS)
            with contextlib.suppress(Exception):
                await send("heartbeat", {"asset": asset})

    async def recv_loop() -> None:
        # We accept only lightweight control frames; anything else is ignored.
        try:
            while not stop.is_set():
                await ws.receive_text()
        except WebSocketDisconnect:
            stop.set()

    tasks = [asyncio.create_task(pump_bus()),
             asyncio.create_task(heartbeat()),
             asyncio.create_task(recv_loop())]
    try:
        await stop.wait()
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
