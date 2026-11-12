"""ETA engine.

Live ETA = remaining distance along the route geometry / blended speed + dwell time
at intermediate stops.

Blended speed uses, in order of availability:
  * observed speed from the bus's recent GPS fixes (progress along the route / time)
  * historical average speed for this route, direction and hour of day
  * the route's configured average speed
then a traffic factor (1.0 unless a TrafficProvider is configured).

If the bus's GPS is stale/offline there is no live ETA; callers fall back to the
timetable and label the result "scheduled".
"""
from __future__ import annotations

import datetime as dt

from ..db import get_db, iso, parse_ts, utcnow
from .network import RouteInfo, network
from .schedule import PK_TZ, next_scheduled_arrivals
from .tracking import active_trip, compute_status, ordered_stops, progress_m, stop_progress

MIN_SPEED, MAX_SPEED = 2.0, 16.0  # m/s clamp (7–58 km/h)


class TrafficProvider:
    """Plug a real traffic feed here (e.g. a licensed traffic API). Returns a multiplier
    applied to travel time: 1.0 = free flow, 1.5 = 50% slower."""

    def factor(self, route: RouteInfo, at: dt.datetime) -> float:
        return 1.0


traffic = TrafficProvider()


def observed_speed(trip: dict, route: RouteInfo) -> float | None:
    since = iso(utcnow() - dt.timedelta(minutes=4))
    pts = get_db().all(
        "SELECT chainage_m, recorded_at FROM gps_locations WHERE trip_id = ? AND recorded_at >= ? AND chainage_m IS NOT NULL "
        "ORDER BY recorded_at DESC LIMIT 12",
        (trip["id"], since),
    )
    if len(pts) < 3:
        return None
    newest, oldest = pts[0], pts[-1]
    span = (parse_ts(newest["recorded_at"]) - parse_ts(oldest["recorded_at"])).total_seconds()
    if span < 20:
        return None
    moved = progress_m(route, newest["chainage_m"], trip["direction"]) - progress_m(route, oldest["chainage_m"], trip["direction"])
    return max(0.0, moved / span)


def historical_speed(route_id: int, direction: str, at: dt.datetime) -> float | None:
    row = get_db().one(
        "SELECT samples, avg_speed_mps FROM segment_speeds WHERE route_id = ? AND direction = ? AND hour = ?",
        (route_id, direction, at.astimezone(PK_TZ).hour),
    )
    return row["avg_speed_mps"] if row and row["samples"] >= 20 else None


def blended_speed(trip: dict, route: RouteInfo, now: dt.datetime) -> tuple[float, dict]:
    obs = observed_speed(trip, route)
    hist = historical_speed(route.id, trip["direction"], now)
    base = hist if hist is not None else route.avg_speed_mps
    if obs is not None:
        # recent movement matters most, but a bus waiting at a signal shouldn't produce an infinite ETA
        v = 0.6 * max(obs, 0.5 * base) + 0.4 * base
    else:
        v = base
    v = max(MIN_SPEED, min(MAX_SPEED, v))
    tf = traffic.factor(route, now)
    return v / tf, {
        "observed_kmh": round(obs * 3.6, 1) if obs is not None else None,
        "historical_kmh": round(hist * 3.6, 1) if hist is not None else None,
        "default_kmh": round(route.avg_speed_mps * 3.6, 1),
        "traffic_factor": tf,
    }


def eta_to_stop(bus: dict, trip: dict | None, route: RouteInfo | None, stop_id: int, now: dt.datetime | None = None) -> dict | None:
    now = now or utcnow()
    if not trip or not route or bus["last_chainage_m"] is None:
        return None
    status, delay = compute_status(bus, trip, route, now)
    if status not in ("active", "delayed"):
        return None
    idx = route.stop_index(stop_id)
    if idx is None:
        return None
    direction = trip["direction"]
    stop = route.stops[idx]
    bus_p = progress_m(route, bus["last_chainage_m"], direction)
    stop_p = stop_progress(route, stop, direction)
    remaining = stop_p - bus_p
    if remaining < -40:
        return None  # already passed
    remaining = max(0.0, remaining)
    speed, sources = blended_speed(trip, route, now)
    dwell = sum(s.dwell_s for s in ordered_stops(route, direction)
                if bus_p + 15 < stop_progress(route, s, direction) < stop_p)
    age = (now - parse_ts(bus["last_gps_at"])).total_seconds()
    eta_s = max(0.0, remaining / speed + dwell - age * 0.5)  # bus kept moving since the last fix
    confidence = "high" if sources["observed_kmh"] is not None and age < 20 else "medium"
    if remaining > 8000:
        confidence = "low" if confidence == "medium" else "medium"
    return {
        "method": "live",
        "eta_s": round(eta_s),
        "eta_at": iso(now + dt.timedelta(seconds=eta_s)),
        "distance_m": round(remaining),
        "confidence": confidence,
        "speed_used_kmh": round(speed * 3.6, 1),
        "sources": sources,
        "delay_min": round(delay, 1),
    }


def arrivals_at_stop(stop_id: int, route_id: int | None = None) -> dict:
    db = get_db()
    now = utcnow()
    routes = [r for r in network.routes_for_stop(stop_id) if route_id is None or r.id == route_id]
    live, scheduled = [], []
    for route in routes:
        live_for_route = 0
        for bus in db.all("SELECT * FROM buses WHERE route_id = ?", (route.id,)):
            trip = active_trip(bus["id"])
            if not trip:
                continue
            last_stop = ordered_stops(route, trip["direction"])[-1]
            eta = eta_to_stop(bus, trip, route, stop_id, now)
            if not eta:
                continue
            live_for_route += 1
            live.append({
                "bus_id": bus["id"], "bus_number": bus["bus_number"], "is_demo": bool(bus["is_demo"]),
                "route_id": route.id, "route_code": route.code, "route_color": route.color,
                "direction": trip["direction"], "towards": last_stop.name,
                "bus_position": {"lat": bus["last_lat"], "lon": bus["last_lon"]},
                "last_gps_at": bus["last_gps_at"],
                **eta,
            })
        if route.status == "active":
            for s in next_scheduled_arrivals(route, stop_id, now, limit=2 if live_for_route else 3):
                scheduled.append({"method": "scheduled", "route_id": route.id, "route_code": route.code,
                                  "route_color": route.color, **s})
    live.sort(key=lambda a: a["eta_s"])
    scheduled.sort(key=lambda a: a["arrival"])
    return {"stop_id": stop_id, "generated_at": iso(now), "live": live, "scheduled": scheduled}
