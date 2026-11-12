"""Public passenger endpoints: no account needed."""
from __future__ import annotations

import asyncio
import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..config import settings
from ..db import get_db, iso, utcnow
from ..errors import ApiError, not_found
from ..geo import haversine
from ..http import api
from ..realtime import hub
from ..schemas import ArrivalsQ, BusesQ, PlanIn, StopSearchQ, StreamQ, TimetableQ
from ..security import decode_token
from ..services import planner
from ..services.eta import arrivals_at_stop, eta_to_stop
from ..services.network import network
from ..services.schedule import PK_TZ, timetable
from ..services.tracking import active_trip, bus_payload, list_buses

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:  # pragma: no cover
    EventSourceResponse = None


@api.get("/api/config", tags=["public"])
def config(ctx):
    """App mode and tracking settings for clients."""
    return {
        "app": settings.app_name, "mode": settings.mode, "demo": settings.is_demo,
        "gps_interval_s": settings.gps_interval_s, "stale_after_s": settings.stale_after_s,
        "offline_after_s": settings.offline_after_s,
        "service_area": {"min_lat": settings.area_min_lat, "max_lat": settings.area_max_lat,
                         "min_lon": settings.area_min_lon, "max_lon": settings.area_max_lon},
        "map": {"center": [31.5204, 74.3587], "zoom": 12,
                "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "© OpenStreetMap contributors"},
        "realtime": {"sse": "/api/live/stream", "websocket": "/ws/live"},
        "push_enabled": settings.fcm_configured,
    }


@api.get("/api/routes", tags=["routes"])
def routes(ctx):
    """All routes with summary info."""
    out = []
    for r in network.routes().values():
        if r.status == "inactive":
            continue
        s = r.summary()
        s["active_buses"] = 0
        out.append(s)
    counts = {}
    for b in list_buses():
        if b["status"] in ("active", "delayed", "stale"):
            counts[b["route_id"]] = counts.get(b["route_id"], 0) + 1
    for s in out:
        s["active_buses"] = counts.get(s["id"], 0)
    return out


@api.get("/api/routes/{id:int}", tags=["routes"])
def route_detail(ctx):
    """Route geometry, ordered stops and live buses."""
    r = network.get(ctx.path["id"])
    if not r or r.status == "inactive":
        raise not_found("Route")
    get_db().insert("route_usage", {"route_id": r.id, "event": "viewed", "created_at": iso()})
    d = r.detail()
    d["buses"] = list_buses([r.id], include_idle=False)
    d["alerts"] = _alerts(route_id=r.id)
    return d


@api.get("/api/stops", query=StopSearchQ, tags=["stops"])
def stops(ctx):
    """Search stops by text and/or proximity (nearest first when lat/lon given)."""
    q = ctx.query
    rows = get_db().all("SELECT id, code, name, name_ur, lat, lon, is_demo FROM stops WHERE status = 'active' ORDER BY name")
    if q.q:
        needle = q.q.lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["code"].lower() or (r["name_ur"] and q.q in r["name_ur"])]
    if q.lat is not None and q.lon is not None:
        for r in rows:
            r["distance_m"] = round(haversine(q.lat, q.lon, r["lat"], r["lon"]))
        rows = sorted([r for r in rows if r["distance_m"] <= q.radius_m], key=lambda r: r["distance_m"])
    for r in rows:
        r["is_demo"] = bool(r["is_demo"])
        r["routes"] = [{"id": rt.id, "code": rt.code, "color": rt.color} for rt in network.routes_for_stop(r["id"]) if rt.status != "inactive"]
    return rows[: q.limit]


@api.get("/api/stops/{id:int}", tags=["stops"])
def stop_detail(ctx):
    """Stop info, routes serving it and alerts."""
    s = get_db().one("SELECT id, code, name, name_ur, lat, lon, is_demo, status FROM stops WHERE id = ?", (ctx.path["id"],))
    if not s:
        raise not_found("Stop")
    s["is_demo"] = bool(s["is_demo"])
    s["routes"] = [r.summary() for r in network.routes_for_stop(s["id"]) if r.status != "inactive"]
    s["alerts"] = _alerts(stop_id=s["id"])
    return s


@api.get("/api/stops/{id:int}/arrivals", query=ArrivalsQ, tags=["eta"])
def stop_arrivals(ctx):
    """Live ETAs of approaching buses, plus timetable estimates (labelled 'scheduled')."""
    if not get_db().one("SELECT id FROM stops WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Stop")
    return arrivals_at_stop(ctx.path["id"], ctx.query.route_id)


@api.get("/api/buses", query=BusesQ, tags=["live"])
def buses(ctx):
    """Current bus positions and status (active, delayed, stale, offline, out_of_service)."""
    return list_buses([ctx.query.route_id] if ctx.query.route_id else None, include_idle=ctx.query.include_idle)


@api.get("/api/buses/{id:int}", tags=["live"])
def bus_detail(ctx):
    """One bus with its route, next stops and ETAs to the remaining stops."""
    db = get_db()
    bus = db.one("SELECT * FROM buses WHERE id = ?", (ctx.path["id"],))
    if not bus:
        raise not_found("Bus")
    trip = active_trip(bus["id"])
    p = bus_payload(bus, trip=trip)
    route = network.get(bus["route_id"])
    upcoming = []
    if route and trip and p["status"] in ("active", "delayed"):
        for s in (route.stops if trip["direction"] == "outbound" else list(reversed(route.stops))):
            eta = eta_to_stop(bus, trip, route, s.stop_id)
            if eta:
                upcoming.append({"stop_id": s.stop_id, "name": s.name, "eta_s": eta["eta_s"], "eta_at": eta["eta_at"],
                                 "distance_m": eta["distance_m"], "confidence": eta["confidence"]})
    p["upcoming_stops"] = upcoming
    if route:
        db.insert("route_usage", {"route_id": route.id, "event": "tracked", "created_at": iso()})
    return p


@api.post("/api/journeys/plan", auth="optional", body=PlanIn, tags=["journeys"], rate=60)
def plan(ctx):
    """Find Speedo routes between two places (with up to one transfer)."""
    db = get_db()

    def resolve(place, default_label):
        if place.stop_id is not None:
            s = db.one("SELECT id, name, lat, lon FROM stops WHERE id = ?", (place.stop_id,))
            if not s:
                raise not_found("Stop")
            return {"lat": s["lat"], "lon": s["lon"], "label": place.label or s["name"], "stop_id": s["id"]}
        return {"lat": place.lat, "lon": place.lon, "label": place.label or default_label}

    o = resolve(ctx.body.origin, "Start")
    d = resolve(ctx.body.destination, "Destination")
    if haversine(o["lat"], o["lon"], d["lat"], d["lon"]) < 150:
        raise ApiError(422, "too_close", "Start and destination are within walking distance")
    result = planner.plan(o, d)
    if ctx.user and ctx.body.save_history and result["options"]:
        db.insert("journey_history", {"user_id": ctx.user_id, "origin_label": o["label"][:160], "dest_label": d["label"][:160],
                                      "route_codes": ",".join(result["options"][0]["route_codes"])[:120], "created_at": iso()})
    return result


@api.get("/api/timetable", query=TimetableQ, tags=["timetable"])
def get_timetable(ctx):
    """Route timetable for a date (default today, Asia/Karachi)."""
    day = ctx.query.date or utcnow().astimezone(PK_TZ).date()
    tt = timetable(ctx.query.route_id, day, ctx.query.stop_id)
    if not tt:
        raise not_found("Route")
    tt["alerts"] = _alerts(route_id=ctx.query.route_id)
    return tt


def _alerts(route_id: int | None = None, stop_id: int | None = None) -> list[dict]:
    now = iso()
    rows = get_db().all(
        "SELECT a.id, a.title, a.body, a.severity, a.route_id, a.stop_id, a.starts_at, a.ends_at, r.code AS route_code "
        "FROM service_alerts a LEFT JOIN routes r ON r.id = a.route_id "
        "WHERE a.is_active = ? AND a.starts_at <= ? AND (a.ends_at IS NULL OR a.ends_at > ?) ORDER BY a.starts_at DESC",
        (True, now, now))
    if route_id is not None:
        rows = [a for a in rows if a["route_id"] in (None, route_id)]
    if stop_id is not None:
        rows = [a for a in rows if a["stop_id"] in (None, stop_id)]
    return rows


@api.get("/api/alerts", tags=["public"])
def alerts(ctx):
    """Active service alerts."""
    return _alerts()


# ------------------------------------------------------------- real time
def _ids(csv: str | None) -> set[int]:
    if not csv:
        return set()
    try:
        return {int(x) for x in csv.split(",") if x.strip()}
    except ValueError:
        raise ApiError(422, "invalid_ids", "ids must be comma-separated integers")


def _channel_for(ticket: str | None) -> str:
    if not ticket:
        return "public"
    claims = decode_token(ticket, typ="stream")
    if not claims or claims.get("role") != "admin":
        raise ApiError(401, "invalid_ticket", "Stream ticket is invalid or expired")
    return "admin"


async def _snapshot(channel: str, route_ids: set[int], bus_ids: set[int]) -> list[dict]:
    buses = await run_in_threadpool(list_buses, route_ids or None, admin=channel == "admin", include_idle=channel == "admin")
    if bus_ids:
        buses = [b for b in buses if b["id"] in bus_ids]
    return buses


@api.get("/api/live/stream", query=StreamQ, tags=["live"])
async def live_stream(ctx):
    """Server-Sent Events stream of bus updates. Events: `snapshot` (all matching buses), `bus` (one bus changed), `ping`."""
    q = ctx.query
    channel = _channel_for(q.ticket)
    route_ids, bus_ids = _ids(q.route_id), _ids(q.bus_id)
    request: Request = ctx.request
    sub = hub.subscribe(channel, route_ids, bus_ids)
    initial = await _snapshot(channel, route_ids, bus_ids)

    async def events():
        try:
            yield {"event": "snapshot", "data": json.dumps({"mode": settings.mode, "buses": initial, "at": iso()})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                    yield {"event": ev["type"], "data": json.dumps(ev)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": json.dumps({"at": iso()})}
        finally:
            hub.unsubscribe(sub)

    if EventSourceResponse is None:
        raise ApiError(501, "sse_unavailable", "Install sse-starlette")
    return EventSourceResponse(events(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def live_websocket(ws: WebSocket):
    """WebSocket alternative to SSE: /ws/live?route_id=1,2&bus_id=3&ticket=..."""
    await ws.accept()
    try:
        channel = _channel_for(ws.query_params.get("ticket"))
        route_ids, bus_ids = _ids(ws.query_params.get("route_id")), _ids(ws.query_params.get("bus_id"))
    except ApiError as e:
        await ws.send_json({"type": "error", "code": e.code, "message": e.message})
        await ws.close(code=4401)
        return
    sub = hub.subscribe(channel, route_ids, bus_ids)
    try:
        await ws.send_json({"type": "snapshot", "mode": settings.mode, "buses": await _snapshot(channel, route_ids, bus_ids)})
        while True:
            try:
                ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                await ws.send_json(ev)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping", "at": iso()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(sub)
