"""Journey planner: walk → ride (→ transfer → ride) → walk over the route network."""
from __future__ import annotations

import datetime as dt

from ..db import get_db, utcnow
from ..geo import haversine
from .eta import eta_to_stop
from .network import RouteInfo, network
from .schedule import PK_TZ, departures, schedules_for, stop_offset_s
from .tracking import active_trip, ordered_stops, scheduled_seconds_to, stop_progress

WALK_MPS = 1.25
WALK_RADIUS_M = 1500
MAX_CANDIDATES = 5
TRANSFER_PENALTY_S = 300


def nearby_stops(lat: float, lon: float, radius_m: float = WALK_RADIUS_M, limit: int = MAX_CANDIDATES) -> list[dict]:
    rows = get_db().all("SELECT id, code, name, name_ur, lat, lon FROM stops WHERE status = 'active'")
    for r in rows:
        r["distance_m"] = round(haversine(lat, lon, r["lat"], r["lon"]))
    rows.sort(key=lambda r: r["distance_m"])
    near = [r for r in rows if r["distance_m"] <= radius_m][:limit]
    return near


def _direction(route: RouteInfo, a: int, b: int) -> str:
    return "outbound" if route.stop_index(a) < route.stop_index(b) else "inbound"


def _ride_seconds(route: RouteInfo, direction: str, a: int, b: int) -> float:
    sa, sb = route.stops[route.stop_index(a)], route.stops[route.stop_index(b)]
    return scheduled_seconds_to(route, direction, stop_progress(route, sb, direction)) - \
        scheduled_seconds_to(route, direction, stop_progress(route, sa, direction))


def _next_bus(route: RouteInfo, stop_id: int, direction: str) -> dict:
    """Live ETA of the next bus heading the right way, else a timetable estimate."""
    db = get_db()
    best = None
    for bus in db.all("SELECT * FROM buses WHERE route_id = ?", (route.id,)):
        trip = active_trip(bus["id"])
        if not trip or trip["direction"] != direction:
            continue
        eta = eta_to_stop(bus, trip, route, stop_id)
        if eta and (best is None or eta["eta_s"] < best["eta_s"]):
            best = {**eta, "bus_id": bus["id"], "bus_number": bus["bus_number"], "is_demo": bool(bus["is_demo"])}
    if best:
        return best
    now = utcnow()
    off = stop_offset_s(route, direction, stop_id) or 0
    local = now.astimezone(PK_TZ)
    for dep in departures(route.id, local.date()):
        arr = dep + dt.timedelta(seconds=round(off))
        if arr >= local:
            return {"method": "scheduled", "eta_s": round((arr - local).total_seconds()), "arrival": arr.isoformat()}
    scheds = schedules_for(route.id, local.date())
    return {"method": "none", "eta_s": None,
            "note": "No more scheduled departures today" if scheds else "No timetable for today"}


def _ride_leg(route: RouteInfo, a: int, b: int) -> dict:
    direction = _direction(route, a, b)
    stops = ordered_stops(route, direction)
    ids = [s.stop_id for s in stops]
    i, j = ids.index(a), ids.index(b)
    seg = stops[i : j + 1]
    secs = _ride_seconds(route, direction, a, b)
    return {
        "kind": "ride",
        "route": {"id": route.id, "code": route.code, "name": route.name, "color": route.color, "is_demo": route.is_demo},
        "direction": direction, "towards": stops[-1].name,
        "board": {"id": seg[0].stop_id, "name": seg[0].name, "lat": seg[0].lat, "lon": seg[0].lon},
        "alight": {"id": seg[-1].stop_id, "name": seg[-1].name, "lat": seg[-1].lat, "lon": seg[-1].lon},
        "stops": [{"id": s.stop_id, "name": s.name, "lat": s.lat, "lon": s.lon} for s in seg],
        "stop_count": len(seg) - 1,
        "distance_km": round(abs(seg[-1].chainage - seg[0].chainage) / 1000, 2),
        "ride_min": round(secs / 60, 1),
        "next_bus": _next_bus(route, seg[0].stop_id, direction),
    }


def _walk(frm: dict, to: dict, dist: float) -> dict:
    return {"kind": "walk", "from": frm.get("name") or frm.get("label"), "to": to.get("name") or to.get("label"),
            "distance_m": round(dist), "walk_min": round(dist / WALK_MPS / 60, 1)}


def plan(origin: dict, dest: dict, max_options: int = 5) -> dict:
    o_c = nearby_stops(origin["lat"], origin["lon"])
    d_c = nearby_stops(dest["lat"], dest["lon"])
    result = {"origin": origin, "destination": dest, "origin_stops": o_c, "destination_stops": d_c, "options": []}
    if not o_c or not d_c:
        result["message"] = ("No Speedo stop within walking distance of your "
                             + ("start" if not o_c else "destination") + f" ({WALK_RADIUS_M / 1000:.1f} km).")
        return result
    routes = [r for r in network.routes().values() if r.status == "active" and r.polyline]
    best: dict[tuple, dict] = {}

    def consider(key, total_s, legs, walk_m, kind):
        if key not in best or total_s < best[key]["total_s"]:
            best[key] = {"type": kind, "total_s": total_s, "walk_m": round(walk_m), "legs": legs}

    for r in routes:
        for o in o_c:
            if r.stop_index(o["id"]) is None:
                continue
            for d in d_c:
                if d["id"] == o["id"] or r.stop_index(d["id"]) is None:
                    continue
                ride = _ride_leg(r, o["id"], d["id"])
                wait = ride["next_bus"]["eta_s"] or 600
                walk_m = o["distance_m"] + d["distance_m"]
                walk_s = o["distance_m"] / WALK_MPS
                wait = max(0, wait - walk_s)
                total = walk_m / WALK_MPS + wait + ride["ride_min"] * 60
                legs = [_walk(origin, o, o["distance_m"]), ride, _walk(d, dest, d["distance_m"])]
                consider(("D", r.id), total, legs, walk_m, "direct")

    if len(best) < 2:  # look for one-transfer journeys
        for r1 in routes:
            for r2 in routes:
                if r1.id == r2.id:
                    continue
                shared = {s.stop_id for s in r1.stops} & {s.stop_id for s in r2.stops}
                if not shared:
                    continue
                for o in o_c:
                    if r1.stop_index(o["id"]) is None:
                        continue
                    for d in d_c:
                        if r2.stop_index(d["id"]) is None:
                            continue
                        for t in shared:
                            if t in (o["id"], d["id"]):
                                continue
                            l1, l2 = _ride_leg(r1, o["id"], t), _ride_leg(r2, t, d["id"])
                            walk_m = o["distance_m"] + d["distance_m"]
                            wait1 = max(0, (l1["next_bus"]["eta_s"] or 600) - o["distance_m"] / WALK_MPS)
                            total = walk_m / WALK_MPS + wait1 + (l1["ride_min"] + l2["ride_min"]) * 60 + TRANSFER_PENALTY_S + 300
                            legs = [_walk(origin, o, o["distance_m"]), l1,
                                    {"kind": "transfer", "at": l1["alight"]["name"], "wait_min": 5}, l2,
                                    _walk(d, dest, d["distance_m"])]
                            consider(("T", r1.id, r2.id), total, legs, walk_m, "transfer")

    opts = sorted(best.values(), key=lambda x: x["total_s"])[:max_options]
    for opt in opts:
        opt["total_min"] = round(opt.pop("total_s") / 60)
        opt["route_codes"] = [l["route"]["code"] for l in opt["legs"] if l["kind"] == "ride"]
    result["options"] = opts
    if not opts:
        result["message"] = "No Speedo route connects these places (with at most one transfer)."
    else:
        db = get_db()
        now = utcnow().isoformat()
        for l in opts[0]["legs"]:
            if l["kind"] == "ride":
                db.insert("route_usage", {"route_id": l["route"]["id"], "event": "planned", "created_at": now})
    return result
