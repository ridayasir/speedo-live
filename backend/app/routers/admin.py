"""Admin dashboard API. Every endpoint requires an admin token."""
import csv
import io
import logging
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

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
    route_stops,
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
from .. import firebase
from ..security import require_admin
from ..services import accounts, importer
from ..services.notifications import notify_route_followers
from ..services.realtime import hub
from ..services.tracking import PKT, aware, bus_state, invalidate_route, recompute_route_metrics, utcnow
from ..store import IntegrityError, Session
from .public import ilike

log = logging.getLogger("speedo.admin")
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
    buses = db.all(Bus)
    states = [bus_state(db, b) for b in buses]
    count = lambda m: len(db.all(m))  # noqa: E731
    active_alerts = [a for a in db.all(ServiceAlert) if a.is_active]
    active_trips = db.where(Trip, status=TripStatus.active)
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
        "active_drivers": len({t.driver_id for t in active_trips if t.driver_id is not None}),
        "ongoing_trips": len(active_trips),
        "passengers": sum(1 for u in db.all(User) if u.role == Role.passenger),
        "alerts": [alert_out(a) for a in active_alerts],
    }


# ----------------------------------------------------------------------------- buses
@router.get("/buses")
def list_buses(q: str | None = None, db: Session = Depends(get_db)):
    buses = sorted(db.all(Bus), key=lambda b: b.bus_number)
    if q:
        buses = [b for b in buses if ilike(q, b.bus_number, b.registration_number)]
    return [bus_admin_out(b) | {"live": bus_state(db, b)} for b in buses]


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
        for t in db.where(Trip, bus_id=b.id, status=TripStatus.active):
            t.status, t.ended_at, t.end_reason = TripStatus.interrupted, utcnow(), "bus_deactivated"
    audit(db, admin, "delete" if hard else "deactivate", "bus", bus_id)
    db.commit()


# ----------------------------------------------------------------------------- stops
@router.get("/stops")
def list_stops(q: str | None = None, db: Session = Depends(get_db)):
    stops = sorted(db.all(BusStop), key=lambda s: s.name)
    if q:
        stops = [s for s in stops if ilike(q, s.name, s.code)]
    counts = Counter(rs.stop_id for rs in route_stops())
    return [stop_out(s) | {"route_count": counts.get(s.id, 0)} for s in stops]


@router.post("/stops", status_code=201)
def create_stop(body: StopIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = BusStop(**body.model_dump())
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
    _commit(db, "stop")
    if body.lat is not None or body.lng is not None:
        for rs in route_stops(stop_id=s.id):
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
    used = len(route_stops(stop_id=stop_id))
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
    found = {i: s for i in ids if (s := db.get(BusStop, i))}
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
    routes = sorted(db.all(Route), key=lambda r: r.code)
    bus_counts = Counter(b.route_id for b in db.all(Bus))
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
    if db.where(Trip, route_id=route_id, status=TripStatus.active):
        raise HTTPException(409, "Route has active trips; end them or suspend the route instead")
    db.delete(r)
    invalidate_route(route_id)
    audit(db, admin, "delete", "route", route_id)
    db.commit()


# ----------------------------------------------------------------------------- schedules
@router.get("/schedules")
def list_schedules(route_id: int | None = None, db: Session = Depends(get_db)):
    rows = sorted(db.all(Schedule), key=lambda s: (s.route_id, s.first_departure))
    if route_id:
        rows = [s for s in rows if s.route_id == route_id]
    return [schedule_out(s) | {"route_code": s.route.code if s.route else None} for s in rows]


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
    rows = sorted((d for d in db.all(Driver) if d.user), key=lambda d: d.user.full_name)
    active = {t.driver_id: t for t in db.where(Trip, status=TripStatus.active)}
    return [driver_out(d) | {"active_trip_id": active[d.id].id if d.id in active else None} for d in rows]


@router.post("/drivers", status_code=201)
def create_driver(body: DriverIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.bus_id and not db.get(Bus, body.bus_id):
        raise HTTPException(400, "Bus not found")
    taken = [x for x in db.all(Driver) if x.license_number == body.license_number
             or (body.employee_code and x.employee_code == body.employee_code)
             or (body.bus_id and x.assigned_bus_id == body.bus_id)]
    if taken:
        raise HTTPException(409, "That driver conflicts with an existing one (duplicate code, number or assignment)")
    user = accounts.create_account(db, body.full_name, body.password, Role.driver, email=body.email, phone=body.phone)
    d = Driver(user_id=user.id, license_number=body.license_number, employee_code=body.employee_code,
               assigned_bus_id=body.bus_id or None)
    db.add(d)
    try:
        _commit(db, "driver")
    except HTTPException:
        firebase.auth_provider.delete_user(user.firebase_uid)
        db.delete(user)
        db.commit()
        raise
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
        d.user.phone = accounts.normalize_phone(data["phone"])
    if "password" in data and data["password"]:
        accounts.set_password(d.user, data["password"])
    for k in ("license_number", "employee_code"):
        if k in data:
            setattr(d, k, data[k])
    if "is_active" in data:
        d.is_active = data["is_active"]
        d.user.is_active = data["is_active"]
        accounts.set_active(d.user, data["is_active"])
        if not data["is_active"]:
            for t in db.where(Trip, driver_id=d.id, status=TripStatus.active):
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
    for b in sorted(db.all(Bus), key=lambda b: b.bus_number):
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
    filters = ([("status", "==", status)] if status else []) + ([("bus_id", "==", bus_id)] if bus_id else [])
    return [trip_out(t) for t in db.where(Trip, *filters, order_by="started_at", desc=True, limit=limit)]


@router.get("/trips/{trip_id}/track")
def trip_track(trip_id: int, db: Session = Depends(get_db)):
    t = db.get(Trip, trip_id)
    if not t:
        raise HTTPException(404, "Trip not found")
    pts = db.where(GpsLocation, trip_id=trip_id, order_by="recorded_at")
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
    return [alert_out(a) for a in sorted(db.all(ServiceAlert), key=lambda a: a.created_at, reverse=True)]


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
    """Import verified route data. Replaces the stop list (and schedules, if given) of each route in the file.

    With Firebase Storage configured, a copy of every uploaded file is kept under imports/ for traceability."""
    uploads = {"routes": (routes_file, await routes_file.read())}
    if schedules_file:
        uploads["schedules"] = (schedules_file, await schedules_file.read())
    if shapes_file:
        uploads["shapes"] = (shapes_file, await shapes_file.read())
    name = lambda k: uploads[k][0].filename or f"{k}.csv"  # noqa: E731
    rows = importer.read_table(name("routes"), uploads["routes"][1])
    shapes = importer.read_table(name("shapes"), uploads["shapes"][1]) if shapes_file else None
    rep = importer.import_routes(db, rows, source_reference, shapes)
    if rep.errors:
        raise HTTPException(422, {"errors": rep.errors[:50]})
    if schedules_file:
        srep = importer.import_schedules(db, importer.read_table(name("schedules"), uploads["schedules"][1]))
        if srep.errors:
            raise HTTPException(422, {"errors": srep.errors[:50], "routes_imported": rep.__dict__})
        rep.schedules = srep.schedules
    stored = {}
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    for kind, (f, data) in uploads.items():
        try:
            path = firebase.files.upload(f"imports/{stamp}_{kind}_{name(kind)}", data, f.content_type)
        except Exception as exc:  # the import itself already succeeded; a missing copy is not fatal
            log.warning("could not store %s in Firebase Storage: %s", kind, exc)
            path = None
        if path:
            stored[kind] = path
    result = {k: v for k, v in rep.__dict__.items() if k != "errors"}
    audit(db, admin, "import", "routes", None, {"source": source_reference, **result, "files": stored})
    db.commit()
    return rep.__dict__ | {"stored_files": stored}


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
    trips = db.where(Trip, ("started_at", ">=", start), ("started_at", "<", end))
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
    journeys = Counter(j.route_id for j in db.where(Journey, ("created_at", ">=", start), ("created_at", "<", end)))
    for code, n in [(r.code, journeys[r.id]) for r in db.all(Route) if journeys.get(r.id)]:
        by_route.setdefault(code, {"route_code": code, "route_name": code, "trips": 0, "journeys": 0, "delayed_trips": 0})["journeys"] = n
    for b in by_bus.values():
        b["km"] = round(b["km"], 1)
        b["hours"] = round(b["hours"], 2)
        b["gps_availability_pct"] = round(min(100.0, 100 * b["gps_points"] / b["expected_points"]), 1) if b["expected_points"] else None
    delayed = [trip_out(t) for t in trips if t.max_delay_minutes >= thr]
    interrupted = [trip_out(t) for t in trips if t.status == TripStatus.interrupted]
    alerts = [a for a in db.all(ServiceAlert) if a.created_at and start <= a.created_at < end]
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
            "default_bus_speed_kmh", "gps_retention_days", "max_walk_m", "firebase_project_id",
            "firebase_storage_bucket"]
    return {k: getattr(s, k) for k in keys} | {"fcm_configured": firebase.push is not None,
                                              "storage_configured": firebase.files.enabled,
                                              "redis_configured": bool(s.redis_url)}


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    rows = db.where(AuditLog, order_by="created_at", desc=True, limit=limit)
    return [{"id": a.id, "user_id": a.user_id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "details": a.details, "created_at": iso(a.created_at)} for a in rows]
