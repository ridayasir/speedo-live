"""Journey planning across routes, with at most one transfer."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import is_sqlite
from ..models import BusStop, Route, RouteStatus, RouteStop
from .geo import haversine_m, point_wkt

TRANSFER_PENALTY_MIN = 5.0


@dataclass
class Place:
    lat: float
    lng: float
    stop_id: int | None = None
    label: str | None = None


def nearby_stops(db: Session, lat: float, lng: float, radius_m: float, limit: int = 8) -> list[tuple[BusStop, float]]:
    if is_sqlite:
        all_stops = [(s, haversine_m(lat, lng, s.lat, s.lng)) for s in db.execute(select(BusStop)).scalars()]
        return sorted((x for x in all_stops if x[1] <= radius_m), key=lambda x: x[1])[:limit]
    geog = func.ST_GeogFromText(point_wkt(lat, lng))
    dist = func.ST_Distance(BusStop.geog, geog).label("d")
    rows = db.execute(
        select(BusStop, dist).where(func.ST_DWithin(BusStop.geog, geog, radius_m)).order_by(dist).limit(limit)
    ).all()
    return [(r[0], float(r[1])) for r in rows]


def _walk_min(m: float) -> float:
    return m / (get_settings().walk_speed_kmh * 1000 / 60)


def _candidates(db: Session, place: Place) -> list[tuple[BusStop, float]]:
    if place.stop_id:
        stop = db.get(BusStop, place.stop_id)
        return [(stop, 0.0)] if stop else []
    found = nearby_stops(db, place.lat, place.lng, get_settings().max_walk_m)
    if not found:  # fall back to the closest few stops, whatever the distance
        found = nearby_stops(db, place.lat, place.lng, 15000, limit=3)
    return found


@dataclass
class RouteIndex:
    route: Route
    by_stop: dict[int, RouteStop]
    ordered: list[RouteStop]
    headway: float

    def ride_minutes(self, a: RouteStop, b: RouteStop) -> float:
        dt = b.offset_minutes - a.offset_minutes
        if dt > 0:
            return dt
        speed = self.route.avg_speed_kmh or get_settings().default_bus_speed_kmh
        return (b.distance_from_start_m - a.distance_from_start_m) / (speed * 1000 / 60)


def _index(db: Session) -> list[RouteIndex]:
    routes = db.execute(select(Route).where(Route.status == RouteStatus.active)).scalars().all()
    out = []
    for r in routes:
        ordered = sorted(r.stops, key=lambda x: x.sequence)
        headways = [s.frequency_minutes for s in r.schedules] or [15]
        out.append(RouteIndex(r, {rs.stop_id: rs for rs in ordered}, ordered, float(min(headways))))
    return out


def _stop_json(s: BusStop) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "lat": s.lat, "lng": s.lng}


def _ride_leg(ri: RouteIndex, a: RouteStop, b: RouteStop) -> dict:
    between = [rs for rs in ri.ordered if a.sequence <= rs.sequence <= b.sequence]
    return {
        "type": "ride",
        "route_id": ri.route.id,
        "route_code": ri.route.code,
        "route_name": ri.route.name,
        "color": ri.route.color,
        "board": _stop_json(a.stop),
        "alight": _stop_json(b.stop),
        "stops": [_stop_json(rs.stop) for rs in between],
        "stop_count": len(between) - 1,
        "distance_m": round(b.distance_from_start_m - a.distance_from_start_m),
        "minutes": round(ri.ride_minutes(a, b), 1),
        "is_demo": ri.route.is_demo,
    }


def _walk_leg(frm: dict, to: dict, meters: float) -> dict:
    return {"type": "walk", "from": frm, "to": to, "distance_m": round(meters), "minutes": round(_walk_min(meters), 1)}


def plan(db: Session, origin: Place, dest: Place, max_options: int = 5) -> dict:
    o_cands = _candidates(db, origin)
    d_cands = _candidates(db, dest)
    idx = _index(db)
    o_pt = {"lat": origin.lat, "lng": origin.lng, "name": origin.label or "Start"}
    d_pt = {"lat": dest.lat, "lng": dest.lng, "name": dest.label or "Destination"}
    options: dict[tuple, dict] = {}

    def add(key: tuple, legs: list[dict], wait: float) -> None:
        total = wait + sum(l["minutes"] for l in legs)
        transfers = sum(1 for l in legs if l["type"] == "ride") - 1
        total += TRANSFER_PENALTY_MIN * transfers
        cur = options.get(key)
        if cur is None or total < cur["total_minutes"]:
            options[key] = {
                "legs": [l for l in legs if l["type"] != "walk" or l["distance_m"] > 0],
                "total_minutes": round(total),
                "wait_minutes": round(wait),
                "transfers": transfers,
                "walk_m": round(sum(l["distance_m"] for l in legs if l["type"] == "walk")),
                "is_demo": any(l.get("is_demo") for l in legs),
            }

    # direct
    for ri in idx:
        for o_stop, o_walk in o_cands:
            a = ri.by_stop.get(o_stop.id)
            if not a:
                continue
            for d_stop, d_walk in d_cands:
                b = ri.by_stop.get(d_stop.id)
                if not b or b.sequence <= a.sequence:
                    continue
                legs = [_walk_leg(o_pt, _stop_json(o_stop), o_walk), _ride_leg(ri, a, b),
                        _walk_leg(_stop_json(d_stop), d_pt, d_walk)]
                add((ri.route.id,), legs, ri.headway / 2)

    # one transfer at a shared stop
    for ra in idx:
        for o_stop, o_walk in o_cands:
            a = ra.by_stop.get(o_stop.id)
            if not a:
                continue
            for rb in idx:
                if rb.route.id == ra.route.id:
                    continue
                for d_stop, d_walk in d_cands:
                    d = rb.by_stop.get(d_stop.id)
                    if not d:
                        continue
                    for x in ra.ordered:
                        if x.sequence <= a.sequence:
                            continue
                        xb = rb.by_stop.get(x.stop_id)
                        if not xb or xb.sequence >= d.sequence:
                            continue
                        legs = [_walk_leg(o_pt, _stop_json(o_stop), o_walk), _ride_leg(ra, a, x),
                                _ride_leg(rb, xb, d), _walk_leg(_stop_json(d_stop), d_pt, d_walk)]
                        add((ra.route.id, rb.route.id), legs, ra.headway / 2 + rb.headway / 2)

    ranked = sorted(options.values(), key=lambda o: (o["total_minutes"], o["transfers"]))
    # drop transfer options that are not better than the best direct one
    best_direct = next((o["total_minutes"] for o in ranked if o["transfers"] == 0), None)
    if best_direct is not None:
        ranked = [o for o in ranked if o["transfers"] == 0 or o["total_minutes"] < best_direct]
    nearest_boarding = _stop_json(o_cands[0][0]) | {"walk_m": round(o_cands[0][1])} if o_cands else None
    nearest_alight = _stop_json(d_cands[0][0]) | {"walk_m": round(d_cands[0][1])} if d_cands else None
    return {
        "origin": o_pt,
        "destination": d_pt,
        "nearest_boarding_stop": nearest_boarding,
        "nearest_destination_stop": nearest_alight,
        "options": ranked[:max_options],
        "straight_line_m": round(haversine_m(origin.lat, origin.lng, dest.lat, dest.lng)),
    }
