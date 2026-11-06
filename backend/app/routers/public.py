"""Public passenger endpoints. No login needed for discovery, tracking or timetables."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (
    Bus,
    BusStop,
    FavoriteRoute,
    Journey,
    Route,
    RouteStatus,
    RouteStop,
    ServiceAlert,
    Trip,
    TripStatus,
)
from ..schemas import PlanIn, alert_out, route_out, schedule_out, stop_out
from ..services.planner import Place, nearby_stops, plan
from ..services.tracking import PKT, arrivals_for_stop, bus_state, schedule_departures, utcnow

router = APIRouter(prefix="/api", tags=["passenger"])


@router.get("/meta")
def meta():
    """Operating mode. In demo mode every bus and route shown is simulated sample data."""
    s = get_settings()
    return {
        "app": "Speedo Live",
        "tagline": "Your Bus, Your Route, Your Time.",
        "data_source": s.data_source,
        "demo_mode": s.is_demo,
        "notice": (
            "DEMO MODE: buses, routes and timings are simulated sample data, not real Speedo services."
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
    stmt = select(Route).order_by(Route.code)
    if not include_inactive:
        stmt = stmt.where(Route.status == RouteStatus.active)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Route.name.ilike(like), Route.code.ilike(like)))
    return [route_out(r, detail=with_path) for r in db.execute(stmt).scalars().all()]


@router.get("/routes/popular")
def popular_routes(limit: int = Query(6, ge=1, le=20), db: Session = Depends(get_db)):
    """Ranked by passenger journeys and favourites in the last 30 days."""
    since = utcnow() - timedelta(days=30)
    j = dict(db.execute(
        select(Journey.route_id, func.count()).where(Journey.created_at >= since).group_by(Journey.route_id)
    ).all())
    f = dict(db.execute(select(FavoriteRoute.route_id, func.count()).group_by(FavoriteRoute.route_id)).all())
    routes = db.execute(select(Route).where(Route.status == RouteStatus.active)).scalars().all()
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
    stmt = select(BusStop).order_by(BusStop.name).limit(limit)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(BusStop.name.ilike(like), BusStop.code.ilike(like), BusStop.name_ur.ilike(like)))
    return [stop_out(s) for s in db.execute(stmt).scalars().all()]


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
    rows = db.execute(select(RouteStop).where(RouteStop.stop_id == stop_id)).scalars().all()
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
    trips = {t.bus_id: t for t in db.execute(select(Trip).where(Trip.status == TripStatus.active)).scalars().all()}
    stmt = select(Bus).order_by(Bus.bus_number)
    buses = db.execute(stmt).scalars().all()
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
    return plan(db, o, d)


# ----------------------------------------------------------------------------- timetable
@router.get("/timetable")
def timetable(route_id: int | None = None, stop_id: int | None = None, db: Session = Depends(get_db)):
    """Route operating hours and scheduled times at major stops (today, Pakistan time)."""
    stmt = select(Route).where(Route.status != RouteStatus.inactive).order_by(Route.code)
    if route_id:
        stmt = stmt.where(Route.id == route_id)
    routes = db.execute(stmt).scalars().all()
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
    stmt = select(ServiceAlert).where(
        ServiceAlert.is_active.is_(True),
        or_(ServiceAlert.starts_at.is_(None), ServiceAlert.starts_at <= now),
        or_(ServiceAlert.ends_at.is_(None), ServiceAlert.ends_at >= now),
    ).order_by(ServiceAlert.created_at.desc())
    if route_id:
        stmt = stmt.where(or_(ServiceAlert.route_id == route_id, ServiceAlert.route_id.is_(None) & ServiceAlert.stop_id.is_(None)))
    if stop_id:
        stmt = stmt.where(or_(ServiceAlert.stop_id == stop_id, ServiceAlert.route_id.is_(None) & ServiceAlert.stop_id.is_(None)))
    return db.execute(stmt).scalars().all()


@router.get("/alerts")
def alerts(route_id: int | None = None, stop_id: int | None = None, db: Session = Depends(get_db)):
    return [alert_out(a) for a in _active_alerts(db, route_id, stop_id)]


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100), db: Session = Depends(get_db)):
    like = f"%{q.strip()}%"
    stops = db.execute(select(BusStop).where(or_(BusStop.name.ilike(like), BusStop.code.ilike(like))).limit(10)).scalars().all()
    routes = db.execute(select(Route).where(or_(Route.name.ilike(like), Route.code.ilike(like))).limit(10)).scalars().all()
    buses = db.execute(select(Bus).where(Bus.bus_number.ilike(like)).limit(10)).scalars().all()
    return {
        "stops": [stop_out(s) for s in stops],
        "routes": [route_out(r) for r in routes],
        "buses": [{"id": b.id, "bus_number": b.bus_number, "route_id": b.route_id, "is_demo": b.is_demo} for b in buses],
    }
