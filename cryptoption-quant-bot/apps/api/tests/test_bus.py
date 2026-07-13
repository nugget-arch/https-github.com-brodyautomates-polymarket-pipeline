"""Unit tests for the in-process event bus and WS envelope."""
from __future__ import annotations

import asyncio

from cryptoption_api.ws.bus import EventBus
from cryptoption_api.ws.events import WsEnvelope


async def test_bus_delivers_to_subscribers():
    bus = EventBus()
    received: list[dict] = []

    async def consume() -> None:
        async for msg in bus.subscribe("chan"):
            received.append(msg)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)  # let the subscriber register
    await bus.publish("chan", {"type": "market.tick", "payload": {"price": 1.0}})
    await bus.publish("chan", {"type": "market.tick", "payload": {"price": 2.0}})
    await asyncio.wait_for(task, timeout=1)
    assert [m["payload"]["price"] for m in received] == [1.0, 2.0]


async def test_bus_isolates_channels():
    bus = EventBus()
    got: list[dict] = []

    async def consume() -> None:
        async for msg in bus.subscribe("a"):
            got.append(msg)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish("b", {"type": "x", "payload": {}})  # different channel
    await bus.publish("a", {"type": "y", "payload": {}})
    await asyncio.wait_for(task, timeout=1)
    assert got[0]["type"] == "y"


def test_envelope_sequence_and_shape():
    e0 = WsEnvelope.make(0, "market.tick", {"price": 1.0})
    e1 = WsEnvelope.make(1, "market.tick", {"price": 2.0})
    assert e0.seq == 0 and e1.seq == 1
    assert e0.type == "market.tick"
    # round-trips through JSON (what the socket sends)
    parsed = WsEnvelope.model_validate_json(e0.model_dump_json())
    assert parsed.payload["price"] == 1.0
