"""GPS ingestion, bus status, progress along routes and ETA calculation."""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Bus, BusStatus, GpsLocation, Route, RouteStop, Schedule, Trip, TripStatus
from .geo import cumulative_lengths, haversine_m, point_wkt, project_onto_path
from .realtime import hub

log = logging.getLogger("speedo.tracking")
PKT = ZoneInfo("Asia/Karachi")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- route cache
@dataclass
class StopOnRoute:
    stop_id: int
    name: str
    sequence: int
    distance_m: float
    offset_minutes: float
    lat: float
    lng: float


@dataclass
class RouteGeom:
    route_id: int
    version: str
    path: list[list[float]]
    cum: list[float]
    stops: list[StopOnRoute]
    avg_speed_kmh: float | None

    @property
    def length_m(self) -> float:
        return self.cum[-1] if self.cum else 0.0

    def offset_at(self, d: float) -> float:
        """Scheduled minutes from route start at distance d (interpolated between stops)."""
        st = self.stops
        if not st:
            return 0.0
        if d <= st[0].distance_m:
            return st[0].offset_minutes
        for a, b in zip(st, st[1:]):
            if d <= b.distance_m:
                span = b.distance_m - a.distance_m
                t = 0 if span <= 0 else (d - a.distance_m) / span
                return a.offset_minutes + t * (b.offset_minutes - a.offset_minutes)
        return st[-1].offset_minutes

    def next_stop(self, d: float) -> StopOnRoute | None:
        for s in self.stops:
            if s.distance_m > d + 25:
                return s
        return None


_route_cache: dict[int, RouteGeom] = {}
_cache_lock = threading.Lock()


def route_geom(db: Session, route: Route | int) -> RouteGeom:
    if isinstance(route, int):
        route = db.get(Route, route)
    version = str(route.updated_at)
    cached = _route_cache.get(route.id)
    if cached and cached.version == version:
        return cached
    rows = db.execute(
        select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
    ).scalars().all()
    path = route.path or [[r.stop.lat, r.stop.lng] for r in rows]
    geom = RouteGeom(
        route_id=route.id,
        version=version,
        path=path,
        cum=cumulative_lengths(path) if path else [0.0],
        stops=[
            StopOnRoute(r.stop_id, r.stop.name, r.sequence, r.distance_from_start_m, r.offset_minutes,
                        r.stop.lat, r.stop.lng)
            for r in rows
        ],
        avg_speed_kmh=route.avg_speed_kmh,
    )
    with _cache_lock:
        _route_cache[route.id] = geom
    return geom


def invalidate_route(route_id: int) -> None:
    with _cache_lock:
        _route_cache.pop(route_id, None)


def recompute_route_metrics(db: Session, route: Route) -> None:
    """Fill distance_from_start_m for each stop and the route length from its path."""
    rows = sorted(route.stops, key=lambda r: r.sequence)
    if not route.path or len(route.path) < 2:
        route.path = [[r.stop.lat, r.stop.lng] for r in rows]
    cum = cumulative_lengths(route.path)
    last = -1.0
    for r in rows:
        p = project_onto_path(r.stop.lat, r.stop.lng, route.path, cum,
                              hint_m=last if last >= 0 else None, window_m=4000)
        # keep stop distances monotonic even on looping roads
        r.distance_from_start_m = max(p.distance_along_m, last + 1 if last >= 0 else 0)
        last = r.distance_from_start_m
    route.length_m = cum[-1] if cum else 0
    if rows:
        route.start_stop_id = rows[0].stop_id
        route.end_stop_id = rows[-1].stop_id
    from .geo import line_wkt

    route.geog = line_wkt(route.path)
    invalidate_route(route.id)


# --------------------------------------------------------------------------- speed memory
_recent: dict[int, deque] = {}


def _remember_progress(bus_id: int, t: datetime, d: float) -> None:
    q = _recent.setdefault(bus_id, deque(maxlen=40))
    q.append((t, d))


def recent_speed_mps(bus_id: int, window_s: int = 180) -> float | None:
    q = _recent.get(bus_id)
    if not q or len(q) < 2:
        return None
    t_end, d_end = q[-1]
    first = next(((t, d) for t, d in q if (t_end - t).total_seconds() <= window_s), q[0])
    dt = (t_end - first[0]).total_seconds()
    if dt < 20:
        return None
    return max(0.0, (d_end - first[1]) / dt)


def clear_progress(bus_id: int) -> None:
    _recent.pop(bus_id, None)


def traffic_factor(route_id: int, at: datetime) -> float:
    """Hook for a real traffic feed. No traffic provider is connected, so no adjustment is made."""
    return 1.0


# --------------------------------------------------------------------------- status
def gps_freshness(bus: Bus, now: datetime | None = None) -> str:
    s = get_settings()
    now = now or utcnow()
    last = aware(bus.last_gps_at)
    if last is None:
        return "none"
    age = (now - last).total_seconds()
    if age <= s.stale_after_seconds:
        return "fresh"
    if age <= s.offline_after_seconds:
        return "stale"
    return "offline"


def active_trip(db: Session, bus_id: int) -> Trip | None:
    return db.execute(
        select(Trip).where(Trip.bus_id == bus_id, Trip.status == TripStatus.active).order_by(Trip.started_at.desc())
    ).scalars().first()


def bus_state(db: Session, bus: Bus, trip: Trip | None = None, now: datetime | None = None,
              find_trip: bool = True) -> dict:
    """Public live state of a bus. Contains no driver personal data."""
    s = get_settings()
    now = now or utcnow()
    if trip is None and find_trip:
        trip = active_trip(db, bus.id)
    fresh = gps_freshness(bus, now)
    last = aware(bus.last_gps_at)
    if bus.status != BusStatus.active:
        status = "out_of_service"
    elif trip is None:
        status = "offline" if fresh != "fresh" else "idle"
    elif fresh == "fresh":
        status = "delayed" if _current_delay(db, trip, now) >= s.delay_threshold_minutes else "active"
    elif fresh == "stale":
        status = "stale"
    else:
        status = "offline"
    motion = None
    if fresh == "fresh" and bus.last_speed_mps is not None:
        motion = "stopped" if bus.last_speed_mps < s.stopped_speed_mps else "moving"

    route_id = trip.route_id if trip else bus.route_id
    next_stop = None
    delay = None
    progress = None
    if trip:
        geom = route_geom(db, trip.route_id)
        progress = trip.progress_m
        ns = geom.next_stop(trip.progress_m)
        if ns:
            next_stop = {"id": ns.stop_id, "name": ns.name, "distance_m": round(ns.distance_m - trip.progress_m)}
        delay = round(_current_delay(db, trip, now), 1)
    return {
        "bus_id": bus.id,
        "bus_number": bus.bus_number,
        "route_id": route_id,
        "trip_id": trip.id if trip else None,
        "lat": bus.last_lat,
        "lng": bus.last_lng,
        "heading": bus.last_heading,
        "speed_kmh": round(bus.last_speed_mps * 3.6, 1) if bus.last_speed_mps is not None else None,
        "accuracy_m": bus.last_accuracy_m,
        "last_gps_at": last.isoformat() if last else None,
        "gps_age_seconds": int((now - last).total_seconds()) if last else None,
        "gps": fresh,
        "status": status,
        "motion": motion,
        "next_stop": next_stop,
        "progress_m": round(progress) if progress is not None else None,
        "delay_minutes": delay,
        "is_demo": bus.is_demo,
        "source": trip.source.value if trip else None,
    }


def _current_delay(db: Session, trip: Trip, now: datetime) -> float:
    geom = route_geom(db, trip.route_id)
    expected = aware(trip.started_at) + timedelta(minutes=geom.offset_at(trip.progress_m))
    ref = aware(trip.last_update_at) or now
    return max(0.0, (ref - expected).total_seconds() / 60)


# --------------------------------------------------------------------------- ingestion
@dataclass
class GpsPoint:
    lat: float
    lng: float
    recorded_at: datetime
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading: float | None = None


@dataclass
class IngestResult:
    accepted: int = 0
    stored: int = 0
    duplicates: int = 0
    rejected: list[dict] = field(default_factory=list)
    state: dict | None = None


def validate_point(p: GpsPoint, now: datetime) -> str | None:
    s = get_settings()
    if not (-90 <= p.lat <= 90 and -180 <= p.lng <= 180):
        return "invalid_coordinates"
    if not (s.area_min_lat <= p.lat <= s.area_max_lat and s.area_min_lng <= p.lng <= s.area_max_lng):
        return "outside_service_area"
    if p.lat == 0 and p.lng == 0:
        return "invalid_coordinates"
    ts = aware(p.recorded_at)
    if ts > now + timedelta(seconds=s.gps_max_future_skew_seconds):
        return "timestamp_in_future"
    if ts < now - timedelta(seconds=s.gps_max_backfill_seconds):
        return "timestamp_too_old"
    if p.accuracy_m is not None and p.accuracy_m > s.gps_max_accuracy_m:
        return "low_accuracy"
    if p.speed_mps is not None and not (0 <= p.speed_mps <= 45):
        return "implausible_speed"
    return None


def ingest_points(db: Session, trip: Trip, points: list[GpsPoint], now: datetime | None = None,
                  broadcast: bool = True) -> IngestResult:
    """Validate, de-duplicate, thin and store GPS points for an active trip, then broadcast."""
    s = get_settings()
    now = now or utcnow()
    res = IngestResult()
    bus = trip.bus
    geom = route_geom(db, trip.route_id)
    last_ts = aware(bus.last_gps_at)
    last_stored = db.execute(
        select(GpsLocation).where(GpsLocation.bus_id == bus.id).order_by(GpsLocation.recorded_at.desc()).limit(1)
    ).scalars().first()

    seen: set[datetime] = set()
    for p in sorted(points, key=lambda x: aware(x.recorded_at)):
        ts = aware(p.recorded_at)
        reason = validate_point(p, now)
        if reason:
            res.rejected.append({"recorded_at": ts.isoformat(), "reason": reason})
            continue
        if ts in seen or (last_ts and ts <= last_ts):
            res.duplicates += 1
            continue
        if last_ts and (ts - last_ts).total_seconds() < s.gps_min_interval_seconds:
            res.duplicates += 1
            continue
        seen.add(ts)
        # teleport guard: > 45 m/s between consecutive points
        if bus.last_lat is not None and last_ts is not None:
            dt = (ts - last_ts).total_seconds()
            jump = haversine_m(bus.last_lat, bus.last_lng, p.lat, p.lng)
            if dt > 0 and jump / dt > 45 and jump > 200:
                res.rejected.append({"recorded_at": ts.isoformat(), "reason": "implausible_jump"})
                continue
            if p.speed_mps is None and dt > 0:
                p.speed_mps = jump / dt
        res.accepted += 1

        proj = project_onto_path(p.lat, p.lng, geom.path, geom.cum, hint_m=trip.progress_m or None)
        if proj.offset_m < 250:
            # buses do not reverse along a one-way route; allow small GPS jitter only
            if proj.distance_along_m >= trip.progress_m - 30:
                trip.progress_m = max(trip.progress_m, proj.distance_along_m)
        _remember_progress(bus.id, ts, trip.progress_m)

        # thinning: keep a point if it moved enough or enough time passed
        keep = (
            last_stored is None
            or haversine_m(last_stored.lat, last_stored.lng, p.lat, p.lng) >= s.gps_store_min_distance_m
            or (ts - aware(last_stored.recorded_at)).total_seconds() >= s.gps_store_min_seconds
        )
        if keep:
            row = GpsLocation(
                trip_id=trip.id, bus_id=bus.id, lat=p.lat, lng=p.lng, geog=point_wkt(p.lat, p.lng),
                accuracy_m=p.accuracy_m, speed_mps=p.speed_mps, heading=p.heading, recorded_at=ts,
            )
            db.add(row)
            last_stored = row
            res.stored += 1

        bus.last_lat, bus.last_lng = p.lat, p.lng
        bus.last_speed_mps = p.speed_mps
        bus.last_heading = p.heading
        bus.last_accuracy_m = p.accuracy_m
        bus.last_gps_at = ts
        last_ts = ts
        trip.last_update_at = ts
        trip.gps_points += 1

    if res.accepted:
        trip.max_delay_minutes = max(trip.max_delay_minutes, _current_delay(db, trip, now))
    db.commit()
    res.state = bus_state(db, bus, trip, now)
    if res.accepted and broadcast:
        hub.publish({"type": "bus_position", **res.state})
    return res


# --------------------------------------------------------------------------- ETA
def live_eta_seconds(db: Session, trip: Trip, stop_distance_m: float) -> float | None:
    s = get_settings()
    remaining = stop_distance_m - trip.progress_m
    if remaining < -25:
        return None  # already passed
    remaining = max(0.0, remaining)
    geom = route_geom(db, trip.route_id)
    hist = geom.avg_speed_kmh or s.default_bus_speed_kmh
    hist_mps = hist / 3.6
    recent = recent_speed_mps(trip.bus_id)
    if recent is None:
        speed = hist_mps
    else:
        # weight recent movement more for nearby stops, history more for far ones
        w = 0.7 if remaining < 2000 else 0.4
        speed = w * max(recent, 1.5) + (1 - w) * hist_mps
    speed = max(speed, 1.5) / traffic_factor(trip.route_id, utcnow())
    # dwell time ~20 s per intermediate stop
    stops_between = sum(1 for st in geom.stops if trip.progress_m + 25 < st.distance_m < stop_distance_m - 25)
    return remaining / speed + 20 * stops_between


def schedule_departures(sched: Schedule, day: datetime) -> list[datetime]:
    """Departures from the first stop for a schedule on a given local (PKT) day."""
    local = day.astimezone(PKT)
    if DAYS[local.weekday()] not in sched.days.split(","):
        return []
    out = []
    start = datetime.combine(local.date(), sched.first_departure, tzinfo=PKT)
    end = datetime.combine(local.date(), sched.last_departure, tzinfo=PKT)
    t = start
    while t <= end:
        out.append(t)
        t += timedelta(minutes=max(1, sched.frequency_minutes))
    return out


def scheduled_arrivals(db: Session, route: Route, stop_offset_min: float, now: datetime, limit: int = 3) -> list[datetime]:
    out: list[datetime] = []
    for sched in route.schedules:
        for day_shift in (0, 1):
            for dep in schedule_departures(sched, now + timedelta(days=day_shift)):
                arr = dep + timedelta(minutes=stop_offset_min)
                if arr >= now:
                    out.append(arr)
    return sorted(out)[:limit]


def arrivals_for_stop(db: Session, stop_id: int, route_id: int | None = None, now: datetime | None = None) -> dict:
    """Upcoming arrivals at a stop. Live estimates only come from fresh GPS; otherwise scheduled times."""
    s = get_settings()
    now = now or utcnow()
    q = select(RouteStop).where(RouteStop.stop_id == stop_id)
    if route_id:
        q = q.where(RouteStop.route_id == route_id)
    rs_rows = db.execute(q).scalars().all()
    live: list[dict] = []
    scheduled: list[dict] = []
    for rs in rs_rows:
        route = rs.route
        trips = db.execute(
            select(Trip).where(Trip.route_id == route.id, Trip.status == TripStatus.active)
        ).scalars().all()
        for trip in trips:
            bus = trip.bus
            fresh = gps_freshness(bus, now)
            secs = live_eta_seconds(db, trip, rs.distance_from_start_m) if fresh == "fresh" else None
            if secs is None:
                continue
            dist = max(0.0, rs.distance_from_start_m - trip.progress_m)
            live.append({
                "kind": "live",
                "route_id": route.id, "route_code": route.code, "route_name": route.name,
                "bus_id": bus.id, "bus_number": bus.bus_number, "trip_id": trip.id,
                "eta": (now + timedelta(seconds=secs)).isoformat(),
                "minutes": max(0, round(secs / 60)),
                "distance_m": round(dist),
                "bus_lat": bus.last_lat, "bus_lng": bus.last_lng,
                "last_gps_at": aware(bus.last_gps_at).isoformat(),
                "is_demo": bus.is_demo,
            })
        for arr in scheduled_arrivals(db, route, rs.offset_minutes, now):
            scheduled.append({
                "kind": "scheduled",
                "route_id": route.id, "route_code": route.code, "route_name": route.name,
                "eta": arr.isoformat(),
                "minutes": max(0, round((arr - now).total_seconds() / 60)),
                "is_demo": route.is_demo,
            })
    live.sort(key=lambda x: x["minutes"])
    scheduled.sort(key=lambda x: x["minutes"])
    return {"stop_id": stop_id, "generated_at": now.isoformat(), "live": live, "scheduled": scheduled[:6],
            "stale_after_seconds": s.stale_after_seconds}


def update_route_history(db: Session, trip: Trip) -> None:
    """Fold a completed trip's average speed into the route's historical speed."""
    if not trip.ended_at or trip.progress_m < 1000:
        return
    secs = (aware(trip.ended_at) - aware(trip.started_at)).total_seconds()
    if secs <= 60:
        return
    kmh = trip.progress_m / secs * 3.6
    if not (3 <= kmh <= 80):
        return
    route = trip.route
    route.avg_speed_kmh = kmh if route.avg_speed_kmh is None else 0.8 * route.avg_speed_kmh + 0.2 * kmh
    invalidate_route(route.id)


def local_time_str(t: time) -> str:
    return t.strftime("%H:%M")
