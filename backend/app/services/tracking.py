"""Trips, GPS ingestion, bus status and the live position feed."""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from typing import Iterable

from ..cache import cache
from ..config import settings
from ..db import get_db, iso, parse_ts, utcnow
from ..errors import ApiError, not_found
from ..geo import haversine, in_service_area
from ..realtime import hub
from .network import RouteInfo, network

log = logging.getLogger("speedo.tracking")
TRIP_ABANDON_S = 30 * 60
_status_memo: dict[int, str] = {}
_memo_lock = threading.Lock()


# --------------------------------------------------------------------- trips
def active_trip(bus_id: int) -> dict | None:
    return get_db().one("SELECT * FROM trips WHERE bus_id = ? AND status = 'active' ORDER BY id DESC", (bus_id,))


def start_trip(bus_id: int, driver_id: int | None, direction: str, source: str) -> dict:
    db = get_db()
    bus = db.one("SELECT * FROM buses WHERE id = ?", (bus_id,))
    if not bus:
        raise not_found("Bus")
    if bus["status"] != "active":
        raise ApiError(409, "bus_not_in_service", f"Bus {bus['bus_number']} is {bus['status']}")
    route = network.get(bus["route_id"])
    if not route or not route.polyline:
        raise ApiError(409, "no_route", "Bus has no assigned route with geometry")
    if route.status != "active":
        raise ApiError(409, "route_not_active", f"Route {route.code} is {route.status}")
    if direction not in ("outbound", "inbound"):
        raise ApiError(422, "invalid_direction", "direction must be outbound or inbound")
    existing = active_trip(bus_id)
    if existing:
        if existing["driver_id"] == driver_id and existing["source"] == source:
            return existing  # resume an interrupted session (app restart, reconnect)
        raise ApiError(409, "trip_already_active", "This bus already has an active trip")
    now = iso()
    trip_id = db.insert("trips", {
        "bus_id": bus_id, "driver_id": driver_id, "route_id": route.id, "direction": direction,
        "status": "active", "source": source, "started_at": now,
    })
    trip = db.one("SELECT * FROM trips WHERE id = ?", (trip_id,))
    publish_bus(bus_id)
    return trip


def end_trip(trip_id: int, status: str = "completed", reason: str = "ended_by_driver") -> dict:
    db = get_db()
    trip = db.one("SELECT * FROM trips WHERE id = ?", (trip_id,))
    if not trip:
        raise not_found("Trip")
    if trip["status"] == "active":
        db.execute("UPDATE trips SET status = ?, ended_at = ?, end_reason = ? WHERE id = ?", (status, iso(), reason, trip_id))
    with _memo_lock:
        _status_memo.pop(trip["bus_id"], None)
    publish_bus(trip["bus_id"])
    return db.one("SELECT * FROM trips WHERE id = ?", (trip_id,))


# ------------------------------------------------------------------ progress
def progress_m(route: RouteInfo, chainage: float, direction: str) -> float:
    return chainage if direction == "outbound" else route.length - chainage


def ordered_stops(route: RouteInfo, direction: str):
    return route.stops if direction == "outbound" else list(reversed(route.stops))


def stop_progress(route: RouteInfo, stop, direction: str) -> float:
    return progress_m(route, stop.chainage, direction)


def next_stop(route: RouteInfo, chainage: float, direction: str):
    p = progress_m(route, chainage, direction)
    for s in ordered_stops(route, direction):
        if stop_progress(route, s, direction) > p + 15:
            return s
    return None


def scheduled_seconds_to(route: RouteInfo, direction: str, target_progress: float) -> float:
    """Planned running time from the trip origin to a point (no traffic)."""
    dwell = sum(s.dwell_s for s in ordered_stops(route, direction)[1:] if stop_progress(route, s, direction) < target_progress)
    return target_progress / route.avg_speed_mps + dwell


def delay_minutes(trip: dict, route: RouteInfo, chainage: float, at=None) -> float:
    at = at or utcnow()
    elapsed = (at - parse_ts(trip["started_at"])).total_seconds()
    expected = scheduled_seconds_to(route, trip["direction"], progress_m(route, chainage, trip["direction"]))
    return max(0.0, (elapsed - expected) / 60)


# -------------------------------------------------------------------- status
def compute_status(bus: dict, trip: dict | None, route: RouteInfo | None, now=None) -> tuple[str, float]:
    """Returns (status, delay_min). Status is one of:
    active | delayed | stale | offline | not_in_service | out_of_service"""
    now = now or utcnow()
    if bus["status"] != "active":
        return "out_of_service", 0.0
    if not trip or not route:
        return "not_in_service", 0.0
    last = parse_ts(trip.get("last_gps_at"))
    ref = last or parse_ts(trip["started_at"])
    age = (now - ref).total_seconds()
    if age > settings.offline_after_s:
        return "offline", 0.0
    if age > settings.stale_after_s or last is None:
        return "stale", 0.0
    delay = delay_minutes(trip, route, bus["last_chainage_m"] or 0, now) if bus["last_chainage_m"] is not None else 0.0
    if delay >= settings.delay_threshold_min:
        return "delayed", delay
    return "active", delay


def bus_payload(bus: dict, *, admin: bool = False, trip: dict | None = None, with_eta: bool = True) -> dict:
    from .eta import eta_to_stop  # local import: eta depends on this module

    now = utcnow()
    trip = trip if trip is not None else active_trip(bus["id"])
    route = network.get(bus["route_id"])
    status, delay = compute_status(bus, trip, route, now)
    last = parse_ts(bus["last_gps_at"])
    has_pos = bus["last_lat"] is not None and trip is not None and last is not None and last >= parse_ts(trip["started_at"])
    out = {
        "id": bus["id"], "bus_number": bus["bus_number"], "is_demo": bool(bus["is_demo"]),
        "route_id": bus["route_id"], "route_code": route.code if route else None,
        "route_name": route.name if route else None, "route_color": route.color if route else None,
        "status": status, "delay_min": round(delay, 1),
        "trip_id": trip["id"] if trip else None, "direction": trip["direction"] if trip else None,
        "position": None, "next_stop": None,
        "last_gps_at": bus["last_gps_at"] if has_pos else None,
        "gps_age_s": round((now - last).total_seconds()) if has_pos else None,
    }
    if has_pos:
        out["position"] = {
            "lat": round(bus["last_lat"], 6), "lon": round(bus["last_lon"], 6),
            "heading": bus["last_heading"], "speed_kmh": round((bus["last_speed_mps"] or 0) * 3.6, 1),
            "moving": (bus["last_speed_mps"] or 0) > 1.0,
            "low_accuracy": (bus["last_accuracy_m"] or 0) > settings.low_accuracy_m,
        }
        if route and bus["last_chainage_m"] is not None and status in ("active", "delayed"):
            ns = next_stop(route, bus["last_chainage_m"], trip["direction"])
            if ns:
                eta = eta_to_stop(bus, trip, route, ns.stop_id) if with_eta else None
                out["next_stop"] = {"id": ns.stop_id, "name": ns.name,
                                    "eta_s": eta["eta_s"] if eta else None,
                                    "distance_m": eta["distance_m"] if eta else None}
    if admin:
        d = None
        if bus["driver_id"]:
            d = get_db().one(
                "SELECT d.id, d.employee_code, u.name, u.phone FROM drivers d JOIN users u ON u.id = d.user_id WHERE d.id = ?",
                (bus["driver_id"],),
            )
        out["driver"] = d
        out["accuracy_m"] = bus["last_accuracy_m"]
        out["bus_status"] = bus["status"]
        out["gps_points"] = trip["gps_points"] if trip else 0
        out["trip_source"] = trip["source"] if trip else None
        out["trip_started_at"] = trip["started_at"] if trip else None
    return out


def list_buses(route_ids: Iterable[int] | None = None, *, admin: bool = False, include_idle: bool = False) -> list[dict]:
    db = get_db()
    rows = db.all("SELECT * FROM buses ORDER BY bus_number")
    trips = {t["bus_id"]: t for t in db.all("SELECT * FROM trips WHERE status = 'active'")}
    rids = set(route_ids or [])
    out = []
    for b in rows:
        if rids and b["route_id"] not in rids:
            continue
        p = bus_payload(b, admin=admin, trip=trips.get(b["id"]))
        if not include_idle and p["status"] in ("not_in_service",):
            continue
        out.append(p)
    return out


def publish_bus(bus_id: int) -> None:
    db = get_db()
    bus = db.one("SELECT * FROM buses WHERE id = ?", (bus_id,))
    if not bus:
        return
    trip = active_trip(bus_id)
    public = bus_payload(bus, trip=trip)
    hub.publish("public", {"type": "bus", "bus": public})
    hub.publish("admin", {"type": "bus", "bus": bus_payload(bus, admin=True, trip=trip, with_eta=False) | {"next_stop": public["next_stop"]}})
    with _memo_lock:
        _status_memo[bus_id] = public["status"]


# ----------------------------------------------------------------- ingestion
def _update_hist_speed(route_id: int, direction: str, hour: int, speed: float) -> None:
    db = get_db()
    row = db.one("SELECT id, samples, avg_speed_mps FROM segment_speeds WHERE route_id = ? AND direction = ? AND hour = ?",
                 (route_id, direction, hour))
    if not row:
        db.insert("segment_speeds", {"route_id": route_id, "direction": direction, "hour": hour, "samples": 1, "avg_speed_mps": speed})
        return
    n = min(row["samples"] + 1, 500)
    avg = row["avg_speed_mps"] + (speed - row["avg_speed_mps"]) / n
    db.execute("UPDATE segment_speeds SET samples = ?, avg_speed_mps = ? WHERE id = ?", (n, avg, row["id"]))


def ingest_points(bus_id: int, trip_id: int, points: list[dict], *, driver_id: int | None = None, source: str = "driver") -> dict:
    """Validate and store GPS fixes for an active trip, update the live position, broadcast."""
    db = get_db()
    bus = db.one("SELECT * FROM buses WHERE id = ?", (bus_id,))
    trip = db.one("SELECT * FROM trips WHERE id = ?", (trip_id,))
    if not bus or not trip or trip["bus_id"] != bus_id:
        raise not_found("Active trip")
    if trip["status"] != "active":
        raise ApiError(409, "trip_not_active", "Trip is not active")
    if source == "driver" and (bus["driver_id"] != driver_id or trip["driver_id"] != driver_id):
        raise ApiError(403, "not_assigned", "You can only share the location of your assigned bus")
    route = network.get(trip["route_id"])
    now = utcnow()
    started = parse_ts(trip["started_at"])
    last_ts = parse_ts(trip["last_gps_at"])
    last_lat, last_lon = bus["last_lat"], bus["last_lon"]
    last_ch = bus["last_chainage_m"] if last_ts else None
    accepted, duplicates, live_updated = 0, 0, False
    rejected: list[dict] = []
    gap_add = 0.0
    dist_add = 0.0
    hist_samples: list[tuple[int, float]] = []
    seen: set[str] = set()

    for idx, p in sorted(enumerate(points), key=lambda ip: parse_ts(ip[1]["recorded_at"])):
        ts = parse_ts(p["recorded_at"])
        key = iso(ts)
        if (ts - now).total_seconds() > settings.max_clock_skew_s:
            rejected.append({"index": idx, "reason": "timestamp_in_future"}); continue
        if (started - ts).total_seconds() > settings.max_clock_skew_s:
            rejected.append({"index": idx, "reason": "before_trip_start"}); continue
        if not in_service_area(p["lat"], p["lon"], settings):
            rejected.append({"index": idx, "reason": "outside_service_area"}); continue
        acc = p.get("accuracy_m")
        if acc is not None and acc > settings.reject_accuracy_m:
            rejected.append({"index": idx, "reason": "accuracy_too_low"}); continue
        if key in seen or (last_ts is not None and ts == last_ts):
            duplicates += 1; continue
        seen.add(key)
        is_live = last_ts is None or ts > last_ts
        if is_live and last_ts is not None and last_lat is not None:
            dt_s = (ts - last_ts).total_seconds()
            dist = haversine(last_lat, last_lon, p["lat"], p["lon"])
            if dt_s > 0 and dist / dt_s > settings.max_bus_speed_mps and dist > 100:
                rejected.append({"index": idx, "reason": "implausible_jump"}); continue
        proj = route.polyline.project(p["lat"], p["lon"], near_chainage=last_ch) if route and route.polyline else None
        ch = proj.chainage if proj else None
        low = acc is not None and acc > settings.low_accuracy_m
        db.insert("gps_locations", {
            "trip_id": trip_id, "bus_id": bus_id, "lat": p["lat"], "lon": p["lon"],
            "speed_mps": p.get("speed_mps"), "heading": p.get("heading"), "accuracy_m": acc,
            "chainage_m": ch, "low_accuracy": low, "recorded_at": key, "received_at": iso(now),
        })
        accepted += 1
        if not is_live:
            continue  # late point from an offline queue: history only
        if last_ts is not None and last_lat is not None:
            dt_s = (ts - last_ts).total_seconds()
            dist_add += haversine(last_lat, last_lon, p["lat"], p["lon"])
            if dt_s > settings.stale_after_s:
                gap_add += dt_s - settings.gps_interval_s
            if ch is not None and last_ch is not None and 3 <= dt_s <= 180:
                along = abs(ch - last_ch)
                v = along / dt_s
                if 0.5 <= v <= settings.max_bus_speed_mps:
                    hist_samples.append((ts.astimezone(_pk_tz()).hour, v))
        speed = p.get("speed_mps")
        if speed is None and last_ts is not None and last_lat is not None:
            dt_s = max(1.0, (ts - last_ts).total_seconds())
            speed = haversine(last_lat, last_lon, p["lat"], p["lon"]) / dt_s
        db.execute(
            "UPDATE buses SET last_lat = ?, last_lon = ?, last_speed_mps = ?, last_heading = ?, last_accuracy_m = ?, "
            "last_chainage_m = ?, last_gps_at = ?, updated_at = ? WHERE id = ?",
            (p["lat"], p["lon"], speed, p.get("heading"), acc, ch, key, iso(now), bus_id),
        )
        last_ts, last_lat, last_lon, last_ch = ts, p["lat"], p["lon"], ch
        live_updated = True

    if accepted:
        db.execute(
            "UPDATE trips SET gps_points = gps_points + ?, last_gps_at = ?, gps_gap_s = gps_gap_s + ?, distance_m = distance_m + ? WHERE id = ?",
            (accepted, iso(last_ts) if last_ts else None, gap_add, dist_add, trip_id),
        )
        for hour, v in hist_samples:
            _update_hist_speed(trip["route_id"], trip["direction"], hour, v)
    if live_updated:
        bus = db.one("SELECT * FROM buses WHERE id = ?", (bus_id,))
        trip = db.one("SELECT * FROM trips WHERE id = ?", (trip_id,))
        if route and bus["last_chainage_m"] is not None:
            d = delay_minutes(trip, route, bus["last_chainage_m"])
            if d > trip["max_delay_min"]:
                db.execute("UPDATE trips SET max_delay_min = ? WHERE id = ?", (d, trip_id))
        cache.set(f"bus:{bus_id}:pos", json.dumps({"lat": bus["last_lat"], "lon": bus["last_lon"], "at": bus["last_gps_at"]}), ttl=3600)
        publish_bus(bus_id)
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected, "live_updated": live_updated}


def _pk_tz():
    from .schedule import PK_TZ
    return PK_TZ


# --------------------------------------------------------------- monitoring
def status_sweep() -> None:
    """Run periodically: broadcast status transitions (stale/offline), count offline events,
    and close trips abandoned for a long time."""
    db = get_db()
    now = utcnow()
    for trip in db.all("SELECT * FROM trips WHERE status = 'active'"):
        bus = db.one("SELECT * FROM buses WHERE id = ?", (trip["bus_id"],))
        if not bus:
            continue
        route = network.get(trip["route_id"])
        status, _ = compute_status(bus, trip, route, now)
        with _memo_lock:
            prev = _status_memo.get(bus["id"])
        if status != prev:
            if status == "offline" and prev != "offline":
                db.execute("UPDATE trips SET offline_events = offline_events + 1 WHERE id = ?", (trip["id"],))
            publish_bus(bus["id"])
        ref = parse_ts(trip["last_gps_at"]) or parse_ts(trip["started_at"])
        if (now - ref).total_seconds() > TRIP_ABANDON_S:
            end_trip(trip["id"], "interrupted", "no_gps_timeout")


def purge_old_locations() -> int:
    cutoff = iso(utcnow() - dt.timedelta(days=settings.gps_retention_days))
    return get_db().execute("DELETE FROM gps_locations WHERE recorded_at < ?", (cutoff,))
