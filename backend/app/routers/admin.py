"""Admin dashboard API. Every endpoint requires an admin token."""
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (
    AuditLog,
    Bus,
    BusStatus,
    BusStop,
    Driver,
    GpsLocation,
    Journey,
    Role,
    Route,
    RouteStatus,
    RouteStop,
    Schedule,
    ServiceAlert,
    Trip,
    TripStatus,
    User,
)
from ..schemas import (
    AlertIn,
    BusIn,
    BusPatch,
    DriverIn,
    DriverPatch,
    RouteIn,
    RoutePatch,
    ScheduleIn,
    StopIn,
    StopPatch,
    alert_out,
    bus_admin_out,
    driver_out,
    iso,
    route_out,
    schedule_out,
    stop_out,
    trip_out,
)
from ..security import hash_password, require_admin
from ..services import importer
from ..services.geo import point_wkt
from ..services.notifications import notify_route_followers
from ..services.realtime import hub
from ..services.tracking import PKT, aware, bus_state, invalidate_route, recompute_route_metrics, utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def audit(db: Session, user: User, action: str, entity: str, entity_id, details: dict | None = None):
    db.add(AuditLog(user_id=user.id, action=action, entity=entity, entity_id=str(entity_id), details=details or {}))


def _commit(db: Session, what: str = "record"):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"That {what} conflicts with an existing one (duplicate code, number or assignment)") from exc


# ----------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    buses = db.execute(select(Bus)).scalars().all()
    states = [bus_state(db, b) for b in buses]
    count = lambda m: db.execute(select(func.count()).select_from(m)).scalar_one()  # noqa: E731
    active_alerts = db.execute(select(ServiceAlert).where(ServiceAlert.is_active.is_(True))).scalars().all()
    return {
        "demo_mode": get_settings().is_demo,
        "total_buses": len(buses),
        "active_buses": sum(1 for s in states if s["status"] in ("active", "delayed")),
        "inactive_buses": sum(1 for b in buses if b.status != BusStatus.active),
        "stale_or_offline": sum(1 for s in states if s["status"] in ("stale", "offline")),
        "delayed_buses": sum(1 for s in states if s["status"] == "delayed"),
        "total_routes": count(Route),
        "total_stops": count(BusStop),
        "total_drivers": count(Driver),
        "active_drivers": db.execute(select(func.count(func.distinct(Trip.driver_id))).where(
            Trip.status == TripStatus.active, Trip.driver_id.is_not(None))).scalar_one(),
        "ongoing_trips": db.execute(select(func.count()).select_from(Trip).where(Trip.status == TripStatus.active)).scalar_one(),
        "passengers": db.execute(select(func.count()).select_from(User).where(User.role == Role.passenger)).scalar_one(),
        "alerts": [alert_out(a) for a in active_alerts],
    }


# ----------------------------------------------------------------------------- buses
@router.get("/buses")
def list_buses(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Bus).order_by(Bus.bus_number)
    if q:
        stmt = stmt.where(or_(Bus.bus_number.ilike(f"%{q}%"), Bus.registration_number.ilike(f"%{q}%")))
    return [bus_admin_out(b) | {"live": bus_state(db, b)} for b in db.execute(stmt).scalars().all()]


@router.post("/buses", status_code=201)
def create_bus(body: BusIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.route_id and not db.get(Route, body.route_id):
        raise HTTPException(400, "Route not found")
    b = Bus(**body.model_dump())
    db.add(b)
    _commit(db, "bus")
    audit(db, admin, "create", "bus", b.id)
    db.commit()
    return bus_admin_out(b)


@router.patch("/buses/{bus_id}")
def update_bus(bus_id: int, body: BusPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.get(Bus, bus_id)
    if not b:
        raise HTTPException(404, "Bus not found")
    data = body.model_dump(exclude_unset=True)
    driver_id = data.pop("driver_id", None)
    if "route_id" in data and data["route_id"] and not db.get(Route, data["route_id"]):
        raise HTTPException(400, "Route not found")
    for k, v in data.items():
        setattr(b, k, v)
    if driver_id is not None:
        if b.driver:
            b.driver.assigned_bus_id = None
            db.flush()
        if driver_id:
            d = db.get(Driver, driver_id)
            if not d:
                raise HTTPException(400, "Driver not found")
            d.assigned_bus_id = b.id
    _commit(db, "bus")
    audit(db, admin, "update", "bus", b.id, {k: str(v) for k, v in body.model_dump(exclude_unset=True).items()})
    db.commit()
    db.refresh(b)
    if b.status != BusStatus.active:
        hub.publish({"type": "bus_status", **bus_state(db, b)})
    return bus_admin_out(b)


@router.delete("/buses/{bus_id}", status_code=204)
def delete_bus(bus_id: int, hard: bool = False, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivates by default (keeps trip history). hard=true deletes the bus and its history."""
    b = db.get(Bus, bus_id)
    if not b:
        raise HTTPException(404, "Bus not found")
    if hard:
        db.delete(b)
    else:
        b.status = BusStatus.inactive
        for t in db.execute(select(Trip).where(Trip.bus_id == b.id, Trip.status == TripStatus.active)).scalars():
            t.status, t.ended_at, t.end_reason = TripStatus.interrupted, utcnow(), "bus_deactivated"
    audit(db, admin, "delete" if hard else "deactivate", "bus", bus_id)
    db.commit()


# ----------------------------------------------------------------------------- stops
@router.get("/stops")
def list_stops(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(BusStop).order_by(BusStop.name)
    if q:
        stmt = stmt.where(or_(BusStop.name.ilike(f"%{q}%"), BusStop.code.ilike(f"%{q}%")))
    stops = db.execute(stmt).scalars().all()
    counts = dict(db.execute(select(RouteStop.stop_id, func.count()).group_by(RouteStop.stop_id)).all())
    return [stop_out(s) | {"route_count": counts.get(s.id, 0)} for s in stops]


@router.post("/stops", status_code=201)
def create_stop(body: StopIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = BusStop(**body.model_dump(), geog=point_wkt(body.lat, body.lng))
    db.add(s)
    _commit(db, "stop")
    audit(db, admin, "create", "stop", s.id)
    db.commit()
    return stop_out(s)


@router.patch("/stops/{stop_id}")
def update_stop(stop_id: int, body: StopPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(BusStop, stop_id)
    if not s:
        raise HTTPException(404, "Stop not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    s.geog = point_wkt(s.lat, s.lng)
    _commit(db, "stop")
    if body.lat is not None or body.lng is not None:
        for rs in db.execute(select(RouteStop).where(RouteStop.stop_id == s.id)).scalars():
            recompute_route_metrics(db, rs.route)
        db.commit()
    audit(db, admin, "update", "stop", s.id)
    db.commit()
    return stop_out(s)


@router.delete("/stops/{stop_id}", status_code=204)
def delete_stop(stop_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(BusStop, stop_id)
    if not s:
        raise HTTPException(404, "Stop not found")
    used = db.execute(select(func.count()).select_from(RouteStop).where(RouteStop.stop_id == stop_id)).scalar_one()
    if used:
        raise HTTPException(409, f"Stop is used by {used} route(s); remove it from those routes first")
    db.delete(s)
    audit(db, admin, "delete", "stop", stop_id)
    db.commit()


# ----------------------------------------------------------------------------- routes
def _apply_stops(db: Session, route: Route, stops) -> None:
    ids = [s.stop_id for s in stops]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "A stop can appear only once on a route")
    found = {s.id: s for s in db.execute(select(BusStop).where(BusStop.id.in_(ids))).scalars()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(400, f"Unknown stop ids: {missing}")
    offsets = [s.offset_minutes for s in stops]
    if offsets != sorted(offsets):
        raise HTTPException(400, "Stop offset_minutes must not decrease along the route")
    route.stops.clear()
    db.flush()
    for n, s in enumerate(stops):
        route.stops.append(RouteStop(stop_id=s.stop_id, stop=found[s.stop_id], sequence=n + 1,
                                     offset_minutes=s.offset_minutes, is_major=s.is_major))
    db.flush()


@router.get("/routes")
def list_routes(db: Session = Depends(get_db)):
    routes = db.execute(select(Route).order_by(Route.code)).scalars().all()
    bus_counts = dict(db.execute(select(Bus.route_id, func.count()).group_by(Bus.route_id)).all())
    return [route_out(r) | {"bus_count": bus_counts.get(r.id, 0), "schedule_count": len(r.schedules)} for r in routes]


@router.get("/routes/{route_id}")
def get_route(route_id: int, db: Session = Depends(get_db)):
    r = db.get(Route, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    return route_out(r, detail=True)


@router.post("/routes", status_code=201)
def create_route(body: RouteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"stops", "path"})
    r = Route(**data, path=body.path or [])
    db.add(r)
    _commit(db, "route")
    _apply_stops(db, r, body.stops)
    recompute_route_metrics(db, r)
    audit(db, admin, "create", "route", r.id)
    _commit(db, "route")
    db.refresh(r)
    return route_out(r, detail=True)


@router.patch("/routes/{route_id}")
def update_route(route_id: int, body: RoutePatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Route, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    data = body.model_dump(exclude_unset=True, exclude={"stops"})
    for k, v in data.items():
        setattr(r, k, v)
    if body.stops is not None:
        _apply_stops(db, r, body.stops)
    if body.stops is not None or "path" in data:
        if body.path is None and "path" in data:
            r.path = []
        recompute_route_metrics(db, r)
    r.updated_at = utcnow()
    _commit(db, "route")
    invalidate_route(r.id)
    audit(db, admin, "update", "route", r.id)
    db.commit()
    db.refresh(r)
    return route_out(r, detail=True)


@router.delete("/routes/{route_id}", status_code=204)
def delete_route(route_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Route, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    if db.execute(select(Trip).where(Trip.route_id == route_id, Trip.status == TripStatus.active)).first():
        raise HTTPException(409, "Route has active trips; end them or suspend the route instead")
    db.delete(r)
    invalidate_route(route_id)
    audit(db, admin, "delete", "route", route_id)
    db.commit()


# ----------------------------------------------------------------------------- schedules
@router.get("/schedules")
def list_schedules(route_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Schedule).order_by(Schedule.route_id, Schedule.first_departure)
    if route_id:
        stmt = stmt.where(Schedule.route_id == route_id)
    return [schedule_out(s) | {"route_code": s.route.code} for s in db.execute(stmt).scalars().all()]


@router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not db.get(Route, body.route_id):
        raise HTTPException(400, "Route not found")
    s = Schedule(**body.model_dump())
    db.add(s)
    db.commit()
    audit(db, admin, "create", "schedule", s.id)
    notify_route_followers(db, s.route_id, "schedule_change", f"Timetable updated: {s.route.code}",
                           f"The timetable for {s.route.name} has changed.", dedupe_key=f"sched:{s.route_id}:{s.id}")
    db.commit()
    return schedule_out(s)


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    audit(db, admin, "update", "schedule", s.id)
    notify_route_followers(db, s.route_id, "schedule_change", f"Timetable updated: {s.route.code}",
                           f"The timetable for {s.route.name} has changed.",
                           dedupe_key=f"sched:{s.route_id}:{s.id}:{utcnow():%Y%m%d%H%M}")
    db.commit()
    return schedule_out(s)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    db.delete(s)
    audit(db, admin, "delete", "schedule", schedule_id)
    db.commit()


# ----------------------------------------------------------------------------- drivers
@router.get("/drivers")
def list_drivers(db: Session = Depends(get_db)):
    rows = db.execute(select(Driver).join(User).order_by(User.full_name)).scalars().all()
    active = {t.driver_id: t for t in db.execute(select(Trip).where(Trip.status == TripStatus.active)).scalars()}
    return [driver_out(d) | {"active_trip_id": active[d.id].id if d.id in active else None} for d in rows]


@router.post("/drivers", status_code=201)
def create_driver(body: DriverIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .auth import _normalize_phone

    user = User(full_name=body.full_name, email=body.email.lower() if body.email else None,
                phone=_normalize_phone(body.phone), password_hash=hash_password(body.password), role=Role.driver)
    db.add(user)
    _commit(db, "driver account")
    d = Driver(user_id=user.id, license_number=body.license_number, employee_code=body.employee_code)
    if body.bus_id:
        if not db.get(Bus, body.bus_id):
            raise HTTPException(400, "Bus not found")
        d.assigned_bus_id = body.bus_id
    db.add(d)
    _commit(db, "driver")
    audit(db, admin, "create", "driver", d.id)
    db.commit()
    db.refresh(d)
    return driver_out(d)


@router.patch("/drivers/{driver_id}")
def update_driver(driver_id: int, body: DriverPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Driver, driver_id)
    if not d:
        raise HTTPException(404, "Driver not found")
    data = body.model_dump(exclude_unset=True)
    if "full_name" in data:
        d.user.full_name = data["full_name"]
    if "phone" in data:
        from .auth import _normalize_phone

        d.user.phone = _normalize_phone(data["phone"])
    if "password" in data and data["password"]:
        d.user.password_hash = hash_password(data["password"])
    for k in ("license_number", "employee_code"):
        if k in data:
            setattr(d, k, data[k])
    if "is_active" in data:
        d.is_active = data["is_active"]
        d.user.is_active = data["is_active"]
        if not data["is_active"]:
            for t in db.execute(select(Trip).where(Trip.driver_id == d.id, Trip.status == TripStatus.active)).scalars():
                t.status, t.ended_at, t.end_reason = TripStatus.interrupted, utcnow(), "driver_deactivated"
    if "bus_id" in data:
        if data["bus_id"]:
            bus = db.get(Bus, data["bus_id"])
            if not bus:
                raise HTTPException(400, "Bus not found")
            if bus.driver and bus.driver.id != d.id:
                bus.driver.assigned_bus_id = None
                db.flush()
            d.assigned_bus_id = bus.id
        else:
            d.assigned_bus_id = None
    if data.get("route_id"):
        if not d.assigned_bus_id:
            raise HTTPException(400, "Assign a bus before assigning a route")
        if not db.get(Route, data["route_id"]):
            raise HTTPException(400, "Route not found")
        db.flush()
        db.get(Bus, d.assigned_bus_id).route_id = data["route_id"]
    _commit(db, "driver")
    audit(db, admin, "update", "driver", d.id, {k: str(v) for k, v in data.items() if k != "password"})
    db.commit()
    db.refresh(d)
    return driver_out(d)


# ----------------------------------------------------------------------------- live fleet & trips
@router.get("/fleet")
def fleet(db: Session = Depends(get_db)):
    """Live fleet with assigned driver names (admin only)."""
    out = []
    for b in db.execute(select(Bus).order_by(Bus.bus_number)).scalars().all():
        st = bus_state(db, b)
        trip = db.get(Trip, st["trip_id"]) if st["trip_id"] else None
        out.append(st | {
            "route_code": b.route.code if b.route else None,
            "route_name": b.route.name if b.route else None,
            "assigned_driver": {"id": b.driver.id, "name": b.driver.user.full_name, "phone": b.driver.user.phone} if b.driver else None,
            "trip": trip_out(trip) if trip else None,
        })
    return {"generated_at": utcnow().isoformat(), "buses": out}


@router.get("/trips")
def list_trips(status: TripStatus | None = None, bus_id: int | None = None, limit: int = Query(100, le=500),
               db: Session = Depends(get_db)):
    stmt = select(Trip).order_by(Trip.started_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Trip.status == status)
    if bus_id:
        stmt = stmt.where(Trip.bus_id == bus_id)
    return [trip_out(t) for t in db.execute(stmt).scalars().all()]


@router.get("/trips/{trip_id}/track")
def trip_track(trip_id: int, db: Session = Depends(get_db)):
    t = db.get(Trip, trip_id)
    if not t:
        raise HTTPException(404, "Trip not found")
    pts = db.execute(select(GpsLocation).where(GpsLocation.trip_id == trip_id).order_by(GpsLocation.recorded_at)).scalars().all()
    return trip_out(t) | {"points": [{"lat": p.lat, "lng": p.lng, "at": iso(p.recorded_at), "speed_mps": p.speed_mps} for p in pts]}


@router.post("/trips/{trip_id}/end")
def force_end_trip(trip_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(Trip, trip_id)
    if not t:
        raise HTTPException(404, "Trip not found")
    if t.status == TripStatus.active:
        t.status, t.ended_at, t.end_reason = TripStatus.interrupted, utcnow(), "ended_by_admin"
        audit(db, admin, "end", "trip", t.id)
        db.commit()
        hub.publish({"type": "trip_ended", **bus_state(db, t.bus, find_trip=False)})
    return trip_out(t)


# ----------------------------------------------------------------------------- alerts
@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db)):
    return [alert_out(a) for a in db.execute(select(ServiceAlert).order_by(ServiceAlert.created_at.desc())).scalars()]


@router.post("/alerts", status_code=201)
def create_alert(body: AlertIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = ServiceAlert(**body.model_dump(), created_by=admin.id)
    db.add(a)
    db.commit()
    if a.route_id and a.severity.value in ("warning", "disruption"):
        notify_route_followers(db, a.route_id, "disruption", a.title, a.message, dedupe_key=f"alert:{a.id}")
    audit(db, admin, "create", "alert", a.id)
    db.commit()
    hub.publish({"type": "alert", **alert_out(a)})
    return alert_out(a)


@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(ServiceAlert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    audit(db, admin, "update", "alert", a.id)
    db.commit()
    hub.publish({"type": "alert", **alert_out(a)})
    return alert_out(a)


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(ServiceAlert, alert_id)
    if a:
        db.delete(a)
        audit(db, admin, "delete", "alert", alert_id)
        db.commit()


# ----------------------------------------------------------------------------- import
@router.post("/import/routes")
async def import_routes(
    routes_file: UploadFile = File(..., description="CSV or XLSX, one row per stop"),
    source_reference: str = Form(..., min_length=3, description="Where this data comes from, e.g. 'PMA route list Oct 2026'"),
    schedules_file: UploadFile | None = File(None),
    shapes_file: UploadFile | None = File(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Import verified route data. Replaces the stop list (and schedules, if given) of each route in the file."""
    rows = importer.read_table(routes_file.filename or "routes.csv", await routes_file.read())
    shapes = importer.read_table(shapes_file.filename or "shapes.csv", await shapes_file.read()) if shapes_file else None
    rep = importer.import_routes(db, rows, source_reference, shapes)
    if rep.errors:
        raise HTTPException(422, {"errors": rep.errors[:50]})
    if schedules_file:
        srep = importer.import_schedules(db, importer.read_table(schedules_file.filename or "s.csv", await schedules_file.read()))
        if srep.errors:
            raise HTTPException(422, {"errors": srep.errors[:50], "routes_imported": rep.__dict__})
        rep.schedules = srep.schedules
    audit(db, admin, "import", "routes", None, {"source": source_reference, **{k: v for k, v in rep.__dict__.items() if k != "errors"}})
    db.commit()
    return rep.__dict__


@router.get("/import/templates/{kind}")
def import_template(kind: str):
    heads = {
        "routes": "route_code,route_name,sequence,stop_code,stop_name,lat,lng,offset_minutes,is_major,color,stop_name_ur\n",
        "schedules": "route_code,days,first_departure,last_departure,frequency_minutes,notes\n",
        "shapes": "route_code,sequence,lat,lng\n",
    }
    if kind not in heads:
        raise HTTPException(404, "Unknown template")
    return StreamingResponse(iter([heads[kind]]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{kind}_template.csv"'})


# ----------------------------------------------------------------------------- reports
def _report(db: Session, start: datetime, end: datetime) -> dict:
    trips = db.execute(select(Trip).where(Trip.started_at >= start, Trip.started_at < end)).scalars().all()
    thr = get_settings().delay_threshold_minutes
    by_day: dict[str, dict] = {}
    by_bus: dict[str, dict] = {}
    by_route: dict[str, dict] = {}
    for t in trips:
        day = aware(t.started_at).astimezone(PKT).date().isoformat()
        dd = by_day.setdefault(day, {"date": day, "trips": 0, "completed": 0, "interrupted": 0, "delayed": 0})
        dd["trips"] += 1
        dd["completed"] += t.status == TripStatus.completed
        dd["interrupted"] += t.status == TripStatus.interrupted
        dd["delayed"] += t.max_delay_minutes >= thr
        end_t = aware(t.ended_at) or aware(t.last_update_at) or aware(t.started_at)
        dur = max(0.0, (end_t - aware(t.started_at)).total_seconds())
        bb = by_bus.setdefault(t.bus.bus_number, {"bus_number": t.bus.bus_number, "trips": 0, "km": 0.0,
                                                  "hours": 0.0, "gps_points": 0, "expected_points": 0})
        bb["trips"] += 1
        bb["km"] += t.progress_m / 1000
        bb["hours"] += dur / 3600
        bb["gps_points"] += t.gps_points
        bb["expected_points"] += int(dur / 10)  # one fix per ~10 s expected
        rr = by_route.setdefault(t.route.code, {"route_code": t.route.code, "route_name": t.route.name, "trips": 0,
                                                "journeys": 0, "delayed_trips": 0})
        rr["trips"] += 1
        rr["delayed_trips"] += t.max_delay_minutes >= thr
    for code, n in db.execute(select(Route.code, func.count()).join(Journey, Journey.route_id == Route.id)
                              .where(Journey.created_at >= start, Journey.created_at < end).group_by(Route.code)).all():
        by_route.setdefault(code, {"route_code": code, "route_name": code, "trips": 0, "journeys": 0, "delayed_trips": 0})["journeys"] = n
    for b in by_bus.values():
        b["km"] = round(b["km"], 1)
        b["hours"] = round(b["hours"], 2)
        b["gps_availability_pct"] = round(min(100.0, 100 * b["gps_points"] / b["expected_points"]), 1) if b["expected_points"] else None
    delayed = [trip_out(t) for t in trips if t.max_delay_minutes >= thr]
    interrupted = [trip_out(t) for t in trips if t.status == TripStatus.interrupted]
    alerts = db.execute(select(ServiceAlert).where(ServiceAlert.created_at >= start, ServiceAlert.created_at < end)).scalars().all()
    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "daily_trips": sorted(by_day.values(), key=lambda x: x["date"]),
        "bus_activity": sorted(by_bus.values(), key=lambda x: x["bus_number"]),
        "route_usage": sorted(by_route.values(), key=lambda x: -x["trips"]),
        "delayed_trips": delayed[:200],
        "service_interruptions": {"interrupted_trips": interrupted[:200], "alerts": [alert_out(a) for a in alerts]},
        "summary": {"trips": len(trips), "delayed": len(delayed), "interrupted": len(interrupted), "alerts": len(alerts)},
    }


@router.get("/reports")
def reports(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    end = utcnow()
    return _report(db, end - timedelta(days=days), end)


@router.get("/reports/{section}.csv")
def report_csv(section: str, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    end = utcnow()
    rep = _report(db, end - timedelta(days=days), end)
    rows = {"daily_trips": rep["daily_trips"], "bus_activity": rep["bus_activity"], "route_usage": rep["route_usage"],
            "delayed_trips": rep["delayed_trips"],
            "interrupted_trips": rep["service_interruptions"]["interrupted_trips"]}.get(section)
    if rows is None:
        raise HTTPException(404, "Unknown report")
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{section}.csv"'})


# ----------------------------------------------------------------------------- settings
@router.get("/settings")
def settings_view():
    """Non-secret runtime settings (change them through environment variables)."""
    s = get_settings()
    keys = ["data_source", "simulator_tick_seconds", "gps_min_interval_seconds", "gps_max_accuracy_m",
            "stale_after_seconds", "offline_after_seconds", "interrupt_trip_after_seconds", "delay_threshold_minutes",
            "default_bus_speed_kmh", "gps_retention_days", "max_walk_m"]
    return {k: getattr(s, k) for k in keys} | {"fcm_configured": bool(s.fcm_project_id and s.fcm_credentials_file),
                                              "redis_configured": bool(s.redis_url)}


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    return [{"id": a.id, "user_id": a.user_id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "details": a.details, "created_at": iso(a.created_at)} for a in rows]
