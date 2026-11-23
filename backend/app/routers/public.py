"""Public passenger endpoints. No login needed for discovery, tracking or timetables."""
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..config import get_settings
from ..db import get_db
from ..models import (
    Bus,
    BusStop,
    FavoriteRoute,
    Journey,
    Route,
    RouteStatus,
    ServiceAlert,
    Trip,
    TripStatus,
    route_stops,
)
from ..schemas import PlanIn, alert_out, route_out, schedule_out, stop_out
from ..limits import limiter
from ..services.places import search as place_search
from ..services.planner import Place, nearby_stops, plan
from ..services.tracking import PKT, arrivals_for_stop, bus_state, schedule_departures, utcnow
from ..services.textmatch import loose_match
from ..store import Session

router = APIRouter(prefix="/api", tags=["passenger"])


def ilike(q: str, *values: str | None) -> bool:
    """Case-insensitive substring match (the old SQL ILIKE '%q%')."""
    q = q.strip().lower()
    return any(v and q in v.lower() for v in values)


def find_stops(q: str, stops: list) -> list:
    """Stops whose name/code contains q; if none, a loose sound-alike match (Urdu script, other spellings)."""
    hits = [s for s in stops if ilike(q, s.name, s.code, s.name_ur, *(s.aliases or []))]
    return hits or [s for s in stops if loose_match(q, s.name, s.name_ur, *(s.aliases or []))]


@router.get("/meta")
def meta():
    """Operating mode. In demo mode, buses flagged is_demo are simulated."""
    s = get_settings()
    return {
        "app": "Speedo Live",
        "tagline": "Your Bus, Your Route, Your Time.",
        "data_source": s.data_source,
        "demo_mode": s.is_demo,
        "notice": (
            "Some buses are simulated until their GPS is connected."
            if s.is_demo else "Live data from authorised GPS sources."
        ),
        "stale_after_seconds": s.stale_after_seconds,
        "offline_after_seconds": s.offline_after_seconds,
        "service_area": {"min_lat": s.area_min_lat, "max_lat": s.area_max_lat,
                         "min_lng": s.area_min_lng, "max_lng": s.area_max_lng},
        "map_center": [31.5204, 74.3587],
    }


# ----------------------------------------------------------------------------- routes
@router.get("/routes")
def list_routes(q: str | None = None, include_inactive: bool = False, with_path: bool = False,
                db: Session = Depends(get_db)):
    """List routes. with_path=true adds the line geometry and ordered stops for drawing on a map."""
    routes = sorted(db.all(Route), key=lambda r: r.code)
    if not include_inactive:
        routes = [r for r in routes if r.status == RouteStatus.active]
    if q:
        routes = [r for r in routes if ilike(q, r.name, r.code)]
    return [route_out(r, detail=with_path) for r in routes]


@router.get("/routes/popular")
def popular_routes(limit: int = Query(6, ge=1, le=20), db: Session = Depends(get_db)):
    """Ranked by passenger journeys and favourites in the last 30 days."""
    since = utcnow() - timedelta(days=30)
    j = Counter(x.route_id for x in db.where(Journey, ("created_at", ">=", since)))
    f = Counter(x.route_id for x in db.all(FavoriteRoute))
    routes = [r for r in db.all(Route) if r.status == RouteStatus.active]
    routes.sort(key=lambda r: (-(j.get(r.id, 0) + 2 * f.get(r.id, 0)), r.code))
    return [route_out(r) | {"journeys_30d": j.get(r.id, 0), "favorites": f.get(r.id, 0)} for r in routes[:limit]]


@router.get("/routes/{route_id}")
def get_route(route_id: int, db: Session = Depends(get_db)):
    r = db.get(Route, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    out = route_out(r, detail=True)
    out["alerts"] = [alert_out(a) for a in _active_alerts(db, route_id=route_id)]
    return out


@router.get("/routes/{route_id}/buses")
def route_buses(route_id: int, db: Session = Depends(get_db)):
    if not db.get(Route, route_id):
        raise HTTPException(404, "Route not found")
    return _live_buses(db, route_id)


# ----------------------------------------------------------------------------- stops
@router.get("/stops")
def list_stops(q: str | None = None, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    stops = sorted(db.all(BusStop), key=lambda s: s.name)
    if q:
        stops = find_stops(q, stops)
    return [stop_out(s) for s in stops[:limit]]


@router.get("/stops/nearby")
def stops_nearby(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                 radius_m: float = Query(1500, ge=50, le=10000), limit: int = Query(10, ge=1, le=50),
                 db: Session = Depends(get_db)):
    return [stop_out(s) | {"distance_m": round(d)} for s, d in nearby_stops(db, lat, lng, radius_m, limit)]


@router.get("/stops/{stop_id}")
def get_stop(stop_id: int, db: Session = Depends(get_db)):
    s = db.get(BusStop, stop_id)
    if not s:
        raise HTTPException(404, "Stop not found")
    rows = route_stops(stop_id=stop_id)
    return stop_out(s) | {
        "routes": [route_out(rs.route) | {"sequence": rs.sequence} for rs in rows],
        "alerts": [alert_out(a) for a in _active_alerts(db, stop_id=stop_id)],
    }


@router.get("/stops/{stop_id}/arrivals")
def stop_arrivals(stop_id: int, route_id: int | None = None, db: Session = Depends(get_db)):
    """Live ETAs from fresh GPS, plus scheduled times. Scheduled entries are never presented as live."""
    if not db.get(BusStop, stop_id):
        raise HTTPException(404, "Stop not found")
    return arrivals_for_stop(db, stop_id, route_id)


# ----------------------------------------------------------------------------- buses
def _live_buses(db: Session, route_id: int | None = None) -> list[dict]:
    now = utcnow()
    trips = {t.bus_id: t for t in db.where(Trip, status=TripStatus.active)}
    buses = sorted(db.all(Bus), key=lambda b: b.bus_number)
    out = []
    for b in buses:
        t = trips.get(b.id)
        rid = t.route_id if t else b.route_id
        if route_id and rid != route_id:
            continue
        out.append(bus_state(db, b, t, now, find_trip=False))
    return out


@router.get("/buses/live")
def live_buses(route_id: int | None = None, db: Session = Depends(get_db)):
    """Latest state of every bus. Subscribe to /ws/live for updates."""
    return {"generated_at": utcnow().isoformat(), "demo_mode": get_settings().is_demo, "buses": _live_buses(db, route_id)}


@router.get("/buses/{bus_id}")
def bus_detail(bus_id: int, db: Session = Depends(get_db)):
    b = db.get(Bus, bus_id)
    if not b:
        raise HTTPException(404, "Bus not found")
    state = bus_state(db, b)
    route_id = state["route_id"]
    upcoming = []
    if state["trip_id"] and route_id:
        trip = db.get(Trip, state["trip_id"])
        from ..services.tracking import live_eta_seconds, route_geom

        geom = route_geom(db, route_id)
        for st in geom.stops:
            if st.distance_m <= trip.progress_m + 25:
                continue
            secs = live_eta_seconds(db, trip, st.distance_m) if state["gps"] == "fresh" else None
            upcoming.append({"stop_id": st.stop_id, "name": st.name, "distance_m": round(st.distance_m - trip.progress_m),
                             "minutes": round(secs / 60) if secs is not None else None,
                             "kind": "live" if secs is not None else "unavailable"})
    return state | {"route": route_out(b.route) if b.route else None, "upcoming_stops": upcoming}


# ----------------------------------------------------------------------------- planning
@router.post("/plan")
def plan_journey(body: PlanIn, db: Session = Depends(get_db)):
    """Find Speedo routes between two places (coordinates or stops), with up to one transfer."""
    def place(lat, lng, stop_id, label):
        if stop_id:
            s = db.get(BusStop, stop_id)
            if not s:
                raise HTTPException(404, f"Stop {stop_id} not found")
            return Place(s.lat, s.lng, s.id, label or s.name)
        return Place(lat, lng, None, label)

    o = place(body.from_lat, body.from_lng, body.from_stop_id, body.from_label)
    d = place(body.to_lat, body.to_lng, body.to_stop_id, body.to_label)
    return plan(db, o, d, prefer=body.prefer)


# ----------------------------------------------------------------------------- timetable
@router.get("/timetable")
def timetable(route_id: int | None = None, stop_id: int | None = None, db: Session = Depends(get_db)):
    """Route operating hours and scheduled times at major stops (today, Pakistan time)."""
    routes = sorted((r for r in db.all(Route) if r.status != RouteStatus.inactive), key=lambda r: r.code)
    if route_id:
        routes = [r for r in routes if r.id == route_id]
    now = utcnow()
    today = now.astimezone(PKT)
    out = []
    for r in routes:
        stops = sorted(r.stops, key=lambda x: x.sequence)
        if stop_id and not any(rs.stop_id == stop_id for rs in stops):
            continue
        shown = [rs for rs in stops if rs.is_major or rs.stop_id == stop_id or rs is stops[0] or rs is stops[-1]]
        if stop_id:
            shown = [rs for rs in stops if rs.stop_id == stop_id]
        deps: list[datetime] = []
        for s in r.schedules:
            deps.extend(schedule_departures(s, now))
        deps.sort()
        out.append(route_out(r) | {
            "schedules": [schedule_out(s) for s in r.schedules],
            "operating_today": bool(deps),
            "first_bus": deps[0].strftime("%H:%M") if deps else None,
            "last_bus": deps[-1].strftime("%H:%M") if deps else None,
            "stops": [
                {"stop_id": rs.stop_id, "name": rs.stop.name, "offset_minutes": rs.offset_minutes,
                 "times": [(d + timedelta(minutes=rs.offset_minutes)).strftime("%H:%M") for d in deps][:200]}
                for rs in shown
            ],
            "alerts": [alert_out(a) for a in _active_alerts(db, route_id=r.id)],
        })
    return {"date": today.date().isoformat(), "timezone": "Asia/Karachi", "routes": out}


# ----------------------------------------------------------------------------- alerts & search
def _active_alerts(db: Session, route_id: int | None = None, stop_id: int | None = None):
    now = utcnow()
    rows = [a for a in db.all(ServiceAlert) if a.is_active and (a.starts_at is None or a.starts_at <= now)
            and (a.ends_at is None or a.ends_at >= now)]
    general = lambda a: a.route_id is None and a.stop_id is None  # noqa: E731
    if route_id:
        rows = [a for a in rows if a.route_id == route_id or general(a)]
    if stop_id:
        rows = [a for a in rows if a.stop_id == stop_id or general(a)]
    return sorted(rows, key=lambda a: a.created_at, reverse=True)


@router.get("/alerts")
def alerts(route_id: int | None = None, stop_id: int | None = None, db: Session = Depends(get_db)):
    return [alert_out(a) for a in _active_alerts(db, route_id, stop_id)]


@router.get("/places")
@limiter.limit("20/minute")
def places(request: Request, q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db)):
    """Find a destination by name: Speedo stops first, then any place in Lahore (OpenStreetMap).

    Call this when the passenger presses Search (not on every keystroke): place lookups are rate limited.
    """
    stops = find_stops(q, db.all(BusStop))
    stops.sort(key=lambda s: (not s.name.lower().startswith(q.strip().lower()), s.name))
    out = [{"label": s.name, "lat": s.lat, "lng": s.lng, "kind": "stop", "stop_id": s.id} for s in stops[:4]]
    s = get_settings()
    for p in place_search(q):
        if s.area_min_lat <= p["lat"] <= s.area_max_lat and s.area_min_lng <= p["lng"] <= s.area_max_lng:
            out.append(p)
    return out


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100), db: Session = Depends(get_db)):
    stops = find_stops(q, db.all(BusStop))[:10]
    routes = [r for r in db.all(Route) if ilike(q, r.name, r.code)][:10]
    buses = [b for b in db.all(Bus) if ilike(q, b.bus_number)][:10]
    return {
        "stops": [stop_out(s) for s in stops],
        "routes": [route_out(r) for r in routes],
        "buses": [{"id": b.id, "bus_number": b.bus_number, "route_id": b.route_id, "is_demo": b.is_demo} for b in buses],
    }
