import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from ..config import get_settings
from ..db import SessionLocal
from ..services.realtime import Subscriber, hub

router = APIRouter()


def _ids(v: str | None) -> set[int]:
    if not v:
        return set()
    return {int(x) for x in v.split(",") if x.strip().isdigit()}


def _snapshot(route_ids: set[int], bus_ids: set[int]) -> list[dict]:
    from .public import _live_buses

    with SessionLocal() as db:
        buses = _live_buses(db)
    if route_ids or bus_ids:
        buses = [b for b in buses if b["route_id"] in route_ids or b["bus_id"] in bus_ids]
    return buses


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    """Live bus positions.

    Query: route_id=1,2 and/or bus_id=5 to filter (none = all buses).
    Server sends {"type":"snapshot","buses":[...]} then {"type":"bus_position"|"bus_status"|"trip_started"|"trip_ended"|"alert", ...}.
    Client may send {"subscribe":{"route_ids":[..],"bus_ids":[..]}} to change filters, or "ping".
    """
    await ws.accept()
    sub = Subscriber(ws, _ids(ws.query_params.get("route_id")), _ids(ws.query_params.get("bus_id")))
    key = hub.add(sub)
    try:
        snap = await run_in_threadpool(_snapshot, sub.route_ids, sub.bus_ids)
        await ws.send_text(json.dumps({"type": "snapshot", "demo_mode": get_settings().is_demo, "buses": snap}, default=str))
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_text('{"type":"heartbeat"}')
                continue
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
                continue
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("subscribe"), dict):
                s = data["subscribe"]
                sub.route_ids = {int(x) for x in s.get("route_ids", []) if str(x).isdigit()}
                sub.bus_ids = {int(x) for x in s.get("bus_ids", []) if str(x).isdigit()}
                snap = await run_in_threadpool(_snapshot, sub.route_ids, sub.bus_ids)
                await ws.send_text(json.dumps({"type": "snapshot", "demo_mode": get_settings().is_demo, "buses": snap}, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(key)
