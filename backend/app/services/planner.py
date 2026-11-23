"""Journey planning across routes: direct trips, one transfer, and two transfers when nothing simpler exists.

Honesty rules for what the planner returns:
- walking distances are straight-line estimates (no street routing): every walk leg says estimate_basis="straight_line";
- ride and wait minutes come from the route timetable (stop offsets, headway/2 wait), never from live data:
  timing_basis="timetable_estimate";
- fare is null unless every route in the trip has a fare in the dataset;
- "no_route" means no connection within the search limits (walking radius, transfers), not "no bus in the city".

Transfers: at the same stop, or (for one-change trips) by walking to another stop within max_transfer_walk_m.
A ride leg's "stops" list includes the boarding and the alighting stop.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from ..config import get_settings
from ..models import BusStop, Route, RouteStatus, RouteStop
from ..store import Session
from .geo import haversine_m

TRANSFER_PENALTY_MIN = 5.0
MAX_TRANSFERS = 2
PREFERENCES = ("fastest", "fewer_transfers", "less_walking")
_RANK = {
    "fastest": lambda o: (o["total_minutes"], o["transfers"], o["walk_m"]),
    "fewer_transfers": lambda o: (o["transfers"], o["total_minutes"], o["walk_m"]),
    "less_walking": lambda o: (o["walk_m"], o["transfers"], o["total_minutes"]),
}


@dataclass
class Place:
    lat: float
    lng: float
    stop_id: int | None = None
    label: str | None = None


def nearby_stops(db: Session, lat: float, lng: float, radius_m: float, limit: int = 8) -> list[tuple[BusStop, float]]:
    """Stops within radius_m (great-circle distance), nearest first. Stops are held in memory."""
    found = [(s, haversine_m(lat, lng, s.lat, s.lng)) for s in db.all(BusStop)]
    return sorted((x for x in found if x[1] <= radius_m), key=lambda x: x[1])[:limit]


_near_cache: dict[tuple, dict[int, list[tuple[int, float]]]] = {}


def _neighbours(db: Session, radius_m: float) -> dict[int, list[tuple[int, float]]]:
    """stop id -> [(other stop id, metres)] within radius_m, itself included at 0 m. Grid-bucketed, cached."""
    stops = db.all(BusStop)
    key = (len(stops), sum(s.id for s in stops), round(sum(s.lat + s.lng for s in stops), 4), radius_m)
    if key in _near_cache:
        return _near_cache[key]
    cell = radius_m / 111000  # degrees of latitude per cell
    grid: dict[tuple[int, int], list[BusStop]] = {}
    for s in stops:
        grid.setdefault((math.floor(s.lat / cell), math.floor(s.lng / cell)), []).append(s)
    out: dict[int, list[tuple[int, float]]] = {}
    for s in stops:
        gx, gy = math.floor(s.lat / cell), math.floor(s.lng / cell)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-2, -1, 0, 1, 2):  # a degree of longitude is shorter than a degree of latitude
                for o in grid.get((gx + dx, gy + dy), []):
                    d = 0.0 if o.id == s.id else haversine_m(s.lat, s.lng, o.lat, o.lng)
                    if d <= radius_m:
                        near.append((o.id, d))
        out[s.id] = sorted(near, key=lambda x: x[1])
    _near_cache.clear()
    _near_cache[key] = out
    return out


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
    reverse: bool = False

    @property
    def towards(self) -> str:
        return self.ordered[-1].stop.name if self.ordered and self.ordered[-1].stop else ""

    def ride_minutes(self, a: RouteStop, b: RouteStop) -> float:
        dt = b.offset_minutes - a.offset_minutes
        if dt > 0:
            return dt
        speed = self.route.avg_speed_kmh or get_settings().default_bus_speed_kmh
        return (b.distance_from_start_m - a.distance_from_start_m) / (speed * 1000 / 60)


@dataclass
class _BackStop:
    """A stop seen from the return direction of a two-way route (sequence, distance and minutes counted from the far end)."""
    stop: BusStop
    stop_id: int
    sequence: int
    distance_from_start_m: float
    offset_minutes: float


def _index(db: Session) -> list[RouteIndex]:
    routes = [r for r in db.all(Route) if r.status == RouteStatus.active]
    out = []
    for r in routes:
        ordered = sorted(r.stops, key=lambda x: x.sequence)
        headway = float(min([s.frequency_minutes for s in r.schedules] or [15]))
        out.append(RouteIndex(r, {rs.stop_id: rs for rs in ordered}, ordered, headway))
        if r.bidirectional and len(ordered) > 1:  # buses also run the list backwards (A <-> B)
            length, last_off = ordered[-1].distance_from_start_m, ordered[-1].offset_minutes
            back = [_BackStop(rs.stop, rs.stop_id, i + 1, length - rs.distance_from_start_m, last_off - rs.offset_minutes)
                    for i, rs in enumerate(reversed(ordered))]
            out.append(RouteIndex(r, {bs.stop_id: bs for bs in back}, back, headway, reverse=True))
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
        "direction": "return" if ri.reverse else "forward",
        "towards": ri.towards,
        "board": _stop_json(a.stop),
        "alight": _stop_json(b.stop),
        "stops": [_stop_json(rs.stop) for rs in between],
        "stop_count": len(between) - 1,
        "distance_m": round(b.distance_from_start_m - a.distance_from_start_m),
        "minutes": round(ri.ride_minutes(a, b), 1),
        "is_demo": ri.route.is_demo,
        "fare_pkr": ri.route.fare_pkr,
    }


def _walk_leg(frm: dict, to: dict, meters: float, transfer: bool = False) -> dict:
    leg = {"type": "walk", "from": frm, "to": to, "distance_m": round(meters), "minutes": round(_walk_min(meters), 1),
           "estimate_basis": "straight_line"}
    if transfer:
        leg["transfer"] = True  # walking between two stops to change buses
    return leg


def plan(db: Session, origin: Place, dest: Place, max_options: int = 3, prefer: str = "fastest") -> dict:
    """One recommended trip plus up to two alternatives, ranked by `prefer` (see PREFERENCES)."""
    if prefer not in _RANK:
        prefer = "fastest"
    s = get_settings()
    outside = [side for side, p in (("origin", origin), ("destination", dest))
               if not (s.area_min_lat <= p.lat <= s.area_max_lat and s.area_min_lng <= p.lng <= s.area_max_lng)]
    if outside:  # Speedo runs in Lahore only: do not stretch the search to the nearest stop 50 km away
        return _empty(origin, dest, prefer, "outside_coverage",
                      [{"code": f"{side}_outside_area", "message": f"The {side} is outside the Speedo service area "
                                                                   f"(Lahore)."} for side in outside])
    o_cands = _candidates(db, origin)
    d_cands = _candidates(db, dest)
    idx = _index(db)
    if not idx:
        return _empty(origin, dest, prefer, "data_unavailable",
                      [{"code": "no_routes", "message": "No active Speedo routes are loaded right now."}])
    o_pt = {"lat": origin.lat, "lng": origin.lng, "name": origin.label or "Start"}
    d_pt = {"lat": dest.lat, "lng": dest.lng, "name": dest.label or "Destination"}
    options: dict[tuple, dict] = {}

    def add(key: tuple, legs: list[dict], wait: float) -> None:
        total = wait + sum(l["minutes"] for l in legs)
        transfers = sum(1 for l in legs if l["type"] == "ride") - 1
        total += TRANSFER_PENALTY_MIN * transfers
        cur = options.get(key)
        if cur is None or total < cur["total_minutes"]:
            fares = [l.get("fare_pkr") for l in legs if l["type"] == "ride"]
            stops_key = "|".join(f'{l["board"]["id"]}-{l["route_id"]}-{l["direction"]}-{l["alight"]["id"]}'
                                 for l in legs if l["type"] == "ride")
            options[key] = {
                "itinerary_id": hashlib.sha1(stops_key.encode()).hexdigest()[:12],
                "timing_basis": "timetable_estimate",
                "fare_pkr": sum(fares) if fares and all(f is not None for f in fares) else None,
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
                add(((ri.route.id, ri.reverse),), legs, ri.headway / 2)

    # one transfer: at the same stop, or by walking to a nearby stop
    near = _neighbours(db, get_settings().max_transfer_walk_m)
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
                        for y_id, gap in near.get(x.stop_id, [(x.stop_id, 0.0)]):
                            xb = rb.by_stop.get(y_id)
                            if not xb or xb.sequence >= d.sequence:
                                continue
                            change = [] if y_id == x.stop_id else [
                                _walk_leg(_stop_json(x.stop), _stop_json(xb.stop), gap, transfer=True)]
                            legs = [_walk_leg(o_pt, _stop_json(o_stop), o_walk), _ride_leg(ra, a, x), *change,
                                    _ride_leg(rb, xb, d), _walk_leg(_stop_json(d_stop), d_pt, d_walk)]
                            add(((ra.route.id, ra.reverse), (rb.route.id, rb.reverse)), legs,
                                ra.headway / 2 + rb.headway / 2)

    if not options:  # two transfers (three buses): only searched when nothing simpler exists
        _two_transfers(idx, o_cands, d_cands, o_pt, d_pt, add)

    ranked = sorted(options.values(), key=_RANK[prefer])
    if prefer == "fastest":
        # drop transfer options that are not faster than the best direct one
        best_direct = next((o["total_minutes"] for o in ranked if o["transfers"] == 0), None)
        if best_direct is not None:
            ranked = [o for o in ranked if o["transfers"] == 0 or o["total_minutes"] < best_direct]
    # duration_seconds / total_walk_distance_m: the spec's names for the same timetable / straight-line estimates
    ranked = [dict(o, recommended=(i == 0), duration_seconds=o["total_minutes"] * 60, total_walk_distance_m=o["walk_m"])
              for i, o in enumerate(ranked[:max_options])]
    warnings = []
    for side, cands in (("origin", o_cands), ("destination", d_cands)):
        if not cands:
            warnings.append({"code": f"{side}_no_stop", "message": f"No Speedo stop found near the {side}."})
        elif cands[0][1] > s.max_walk_m:
            warnings.append({"code": f"{side}_far_from_stops", "distance_m": round(cands[0][1]),
                             "message": f"The nearest Speedo stop is {cands[0][1] / 1000:.1f} km from the {side} "
                                        f"(straight line)."})
    nearest_boarding = _stop_json(o_cands[0][0]) | {"walk_m": round(o_cands[0][1])} if o_cands else None
    nearest_alight = _stop_json(d_cands[0][0]) | {"walk_m": round(d_cands[0][1])} if d_cands else None
    return {
        "origin": o_pt,
        "destination": d_pt,
        "nearest_boarding_stop": nearest_boarding,
        "nearest_destination_stop": nearest_alight,
        "status": "ok" if ranked else "no_route",
        "prefer": prefer,
        "search_limits": {"max_walk_m": round(s.max_walk_m), "max_transfers": MAX_TRANSFERS,
                          "max_transfer_walk_m": round(s.max_transfer_walk_m)},
        "dataset": _dataset_info(idx),
        "warnings": warnings,
        "options": ranked,
        "straight_line_m": round(haversine_m(origin.lat, origin.lng, dest.lat, dest.lng)),
    }


def _two_transfers(idx: list[RouteIndex], o_cands, d_cands, o_pt: dict, d_pt: dict, add, keep: int = 60) -> None:
    """Journeys with three buses. The last bus is precomputed per stop ("best way to finish from here"), so the
    search only walks the first two routes: routes x stops x routes x stops, fine for a city network."""
    import heapq
    import itertools

    tail: dict[int, list[tuple[float, RouteIndex, object, tuple]]] = {}
    for rc in idx:
        for d_stop, d_walk in d_cands:
            d = rc.by_stop.get(d_stop.id)
            if not d:
                continue
            for y in rc.ordered:
                if y.sequence >= d.sequence:
                    break
                cost = rc.headway / 2 + rc.ride_minutes(y, d) + _walk_min(d_walk)
                tail.setdefault(y.stop_id, []).append((cost, rc, y, (d_stop, d_walk, d)))
    for lst in tail.values():
        lst.sort(key=lambda t: t[0])
        del lst[6:]
    if not tail:
        return
    best: list = []
    tie = itertools.count()
    for ra in idx:
        for o_stop, o_walk in o_cands:
            a = ra.by_stop.get(o_stop.id)
            if not a:
                continue
            for x in ra.ordered:
                if x.sequence <= a.sequence:
                    continue
                t1 = _walk_min(o_walk) + ra.headway / 2 + ra.ride_minutes(a, x)
                for rb in idx:
                    if rb.route.id == ra.route.id:
                        continue
                    xb = rb.by_stop.get(x.stop_id)
                    if not xb:
                        continue
                    for y in rb.ordered:
                        if y.sequence <= xb.sequence or y.stop_id not in tail:
                            continue
                        t2 = t1 + rb.headway / 2 + rb.ride_minutes(xb, y)
                        for cost, rc, yc, dinfo in tail[y.stop_id]:
                            if rc.route.id in (ra.route.id, rb.route.id):
                                continue
                            item = (-(t2 + cost), next(tie), (ra, a, o_stop, o_walk, x, rb, xb, y, rc, yc, dinfo))
                            if len(best) < keep:
                                heapq.heappush(best, item)
                            elif item[0] > best[0][0]:
                                heapq.heapreplace(best, item)
                            break  # tail lists are sorted: the first usable one is the best for this stop
    for _, _, (ra, a, o_stop, o_walk, x, rb, xb, y, rc, yc, (d_stop, d_walk, d)) in best:
        legs = [_walk_leg(o_pt, _stop_json(o_stop), o_walk), _ride_leg(ra, a, x), _ride_leg(rb, xb, y),
                _ride_leg(rc, yc, d), _walk_leg(_stop_json(d_stop), d_pt, d_walk)]
        add(((ra.route.id, ra.reverse), (rb.route.id, rb.reverse), (rc.route.id, rc.reverse)), legs,
            ra.headway / 2 + rb.headway / 2 + rc.headway / 2)


def _dataset_info(idx: list[RouteIndex]) -> dict:
    """Where the route data comes from and when it last changed (spec section 2)."""
    routes = {ri.route.id: ri.route for ri in idx}.values()
    sources = sorted({r.source_reference for r in routes if r.source_reference})
    stamps = [r.updated_at for r in routes if getattr(r, "updated_at", None)]
    newest = max(stamps) if stamps else None
    return {"sources": sources[:3], "source_count": len(sources), "route_count": len(routes),
            "updated_at": newest.isoformat() if hasattr(newest, "isoformat") else newest}


def _empty(origin: Place, dest: Place, prefer: str, status: str, warnings: list[dict]) -> dict:
    """A plan with no options and the reason (outside_coverage, data_unavailable)."""
    s = get_settings()
    return {
        "origin": {"lat": origin.lat, "lng": origin.lng, "name": origin.label or "Start"},
        "destination": {"lat": dest.lat, "lng": dest.lng, "name": dest.label or "Destination"},
        "nearest_boarding_stop": None, "nearest_destination_stop": None,
        "status": status, "prefer": prefer,
        "search_limits": {"max_walk_m": round(s.max_walk_m), "max_transfers": MAX_TRANSFERS,
                          "max_transfer_walk_m": round(s.max_transfer_walk_m)},
        "dataset": None, "warnings": warnings, "options": [],
        "straight_line_m": round(haversine_m(origin.lat, origin.lng, dest.lat, dest.lng)),
    }
