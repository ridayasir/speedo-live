"""Administrator endpoints (role: admin)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json

from starlette.responses import PlainTextResponse, Response

from ..cache import cache
from ..config import settings
from ..db import get_db, iso, utcnow
from ..errors import ApiError, not_found
from ..http import api
from ..realtime import hub
from ..schemas import (AlertIn, AlertPatch, BusIn, BusPatch, DriverIn, DriverPatch, ImportQ, ReportQ, RouteIn, RoutePatch,
                       ScheduleIn, StopIn)
from ..security import create_token, hash_password
from ..seed import create_user
from ..services import importer
from ..services.network import network, rebuild_route_geometry
from ..services.notify import notify_route_followers
from ..services.reports import daily_report
from ..services.schedule import PK_TZ
from ..services.tracking import active_trip, end_trip, list_buses, publish_bus

ADMIN = ("admin",)
T = ["admin"]


def _exists(table: str, row_id: int | None, what: str) -> None:
    if row_id is not None and not get_db().one(f"SELECT id FROM {table} WHERE id = ?", (row_id,)):
        raise ApiError(422, f"unknown_{what.lower()}", f"{what} {row_id} does not exist")


# ------------------------------------------------------------- overview
@api.get("/api/admin/overview", auth=ADMIN, tags=T)
def overview(ctx):
    """Dashboard counters."""
    db = get_db()
    buses = list_buses(admin=True, include_idle=True)
    by = lambda *st: sum(1 for b in buses if b["status"] in st)
    return {
        "mode": settings.mode,
        "buses_total": len(buses),
        "buses_active": db.scalar("SELECT COUNT(*) FROM buses WHERE status = 'active'"),
        "buses_inactive": db.scalar("SELECT COUNT(*) FROM buses WHERE status <> 'active'"),
        "routes": db.scalar("SELECT COUNT(*) FROM routes"),
        "stops": db.scalar("SELECT COUNT(*) FROM stops"),
        "drivers_total": db.scalar("SELECT COUNT(*) FROM drivers"),
        "drivers_on_trip": db.scalar("SELECT COUNT(*) FROM trips WHERE status = 'active' AND source = 'driver'"),
        "ongoing_trips": db.scalar("SELECT COUNT(*) FROM trips WHERE status = 'active'"),
        "live": {"active": by("active"), "delayed": by("delayed"), "stale": by("stale"), "offline": by("offline"),
                 "out_of_service": by("out_of_service"), "not_in_service": by("not_in_service")},
        "alerts_active": db.scalar("SELECT COUNT(*) FROM service_alerts WHERE is_active = ? AND (ends_at IS NULL OR ends_at > ?)", (True, iso())),
        "realtime_subscribers": hub.subscriber_count,
        "complaints_open": db.scalar("SELECT COUNT(*) FROM complaints WHERE status IN ('new','in_review')"),
    }


@api.post("/api/admin/stream-ticket", auth=ADMIN, tags=T)
def stream_ticket(ctx):
    """Short-lived ticket for the admin live stream (EventSource can't send headers)."""
    return {"ticket": create_token(ctx.user_id, "admin", typ="stream", ttl_s=120), "expires_in": 120}


@api.get("/api/admin/fleet", auth=ADMIN, tags=T)
def fleet(ctx):
    """All buses with driver, GPS and trip details."""
    return list_buses(admin=True, include_idle=True)


# ----------------------------------------------------------------- buses
@api.get("/api/admin/buses", auth=ADMIN, tags=T)
def admin_buses(ctx):
    """List buses."""
    return get_db().all(
        "SELECT b.id, b.bus_number, b.registration_no, b.capacity, b.route_id, r.code AS route_code, b.driver_id, u.name AS driver_name, "
        "b.status, b.is_demo, b.gps_device_id, b.last_gps_at FROM buses b LEFT JOIN routes r ON r.id = b.route_id "
        "LEFT JOIN drivers d ON d.id = b.driver_id LEFT JOIN users u ON u.id = d.user_id ORDER BY b.bus_number")


def _check_bus_refs(route_id, driver_id, bus_id=None):
    _exists("routes", route_id, "Route")
    _exists("drivers", driver_id, "Driver")
    if driver_id is not None:
        other = get_db().one("SELECT bus_number FROM buses WHERE driver_id = ? AND id <> ?", (driver_id, bus_id or 0))
        if other:
            raise ApiError(409, "driver_busy", f"That driver is already assigned to bus {other['bus_number']}")


@api.post("/api/admin/buses", auth=ADMIN, body=BusIn, tags=T, status=201)
def create_bus(ctx):
    """Add a bus."""
    b, db = ctx.body, get_db()
    if db.one("SELECT id FROM buses WHERE bus_number = ?", (b.bus_number,)):
        raise ApiError(409, "duplicate", "A bus with this number already exists")
    _check_bus_refs(b.route_id, b.driver_id)
    bid = db.insert("buses", {**b.model_dump(), "is_demo": False, "created_at": iso(), "updated_at": iso()})
    return db.one("SELECT * FROM buses WHERE id = ?", (bid,))


@api.patch("/api/admin/buses/{id:int}", auth=ADMIN, body=BusPatch, tags=T)
def update_bus(ctx):
    """Edit a bus, assign route/driver, or change status."""
    db, bid = get_db(), ctx.path["id"]
    bus = db.one("SELECT * FROM buses WHERE id = ?", (bid,))
    if not bus:
        raise not_found("Bus")
    b = ctx.body
    vals = b.model_dump(exclude_unset=True, exclude={"clear_route", "clear_driver"})
    vals = {k: v for k, v in vals.items() if v is not None}
    if b.clear_route:
        vals["route_id"] = None
    if b.clear_driver:
        vals["driver_id"] = None
    _check_bus_refs(vals.get("route_id"), vals.get("driver_id"), bid)
    trip = active_trip(bid)
    if trip and ("route_id" in vals and vals["route_id"] != bus["route_id"] or vals.get("status", "active") != "active"
                 or ("driver_id" in vals and vals["driver_id"] != bus["driver_id"])):
        end_trip(trip["id"], "interrupted", "reassigned_by_admin")
    if "bus_number" in vals and db.one("SELECT id FROM buses WHERE bus_number = ? AND id <> ?", (vals["bus_number"], bid)):
        raise ApiError(409, "duplicate", "A bus with this number already exists")
    db.update("buses", bid, {**vals, "updated_at": iso()})
    publish_bus(bid)
    return db.one("SELECT * FROM buses WHERE id = ?", (bid,))


@api.delete("/api/admin/buses/{id:int}", auth=ADMIN, tags=T)
def delete_bus(ctx):
    """Delete a bus (blocked while it has an active trip; deactivate it instead)."""
    if active_trip(ctx.path["id"]):
        raise ApiError(409, "trip_active", "End the bus's active trip first, or set its status to inactive")
    if not get_db().execute("DELETE FROM buses WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Bus")
    return {"ok": True}


@api.post("/api/admin/trips/{id:int}/end", auth=ADMIN, tags=T)
def admin_end_trip(ctx):
    """Force-end a trip (e.g. a driver forgot to end it)."""
    return end_trip(ctx.path["id"], "interrupted", "ended_by_admin")


# ---------------------------------------------------------------- stops
@api.get("/api/admin/stops", auth=ADMIN, tags=T)
def admin_stops(ctx):
    """List stops with the routes serving them."""
    rows = get_db().all("SELECT * FROM stops ORDER BY name")
    for r in rows:
        r["is_demo"] = bool(r["is_demo"])
        r["routes"] = [rt.code for rt in network.routes_for_stop(r["id"])]
    return rows


@api.post("/api/admin/stops", auth=ADMIN, body=StopIn, tags=T, status=201)
def create_stop(ctx):
    """Add a stop."""
    db = get_db()
    if db.one("SELECT id FROM stops WHERE code = ?", (ctx.body.code,)):
        raise ApiError(409, "duplicate", "A stop with this code already exists")
    sid = db.insert("stops", {**ctx.body.model_dump(), "is_demo": False, "created_at": iso()})
    return db.one("SELECT * FROM stops WHERE id = ?", (sid,))


@api.put("/api/admin/stops/{id:int}", auth=ADMIN, body=StopIn, tags=T)
def update_stop(ctx):
    """Edit a stop (routes using it are re-measured)."""
    db, sid = get_db(), ctx.path["id"]
    if not db.one("SELECT id FROM stops WHERE id = ?", (sid,)):
        raise not_found("Stop")
    if db.one("SELECT id FROM stops WHERE code = ? AND id <> ?", (ctx.body.code, sid)):
        raise ApiError(409, "duplicate", "A stop with this code already exists")
    db.update("stops", sid, ctx.body.model_dump())
    for rid in {r["route_id"] for r in db.all("SELECT route_id FROM route_stops WHERE stop_id = ?", (sid,))}:
        rebuild_route_geometry(rid)
    network.invalidate()
    return db.one("SELECT * FROM stops WHERE id = ?", (sid,))


@api.delete("/api/admin/stops/{id:int}", auth=ADMIN, tags=T)
def delete_stop(ctx):
    """Delete a stop that no route uses."""
    db = get_db()
    used = [rt.code for rt in network.routes_for_stop(ctx.path["id"])]
    if used:
        raise ApiError(409, "stop_in_use", f"Remove the stop from routes first: {', '.join(used)}")
    if not db.execute("DELETE FROM stops WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Stop")
    return {"ok": True}


# --------------------------------------------------------------- routes
@api.get("/api/admin/routes", auth=ADMIN, tags=T)
def admin_routes(ctx):
    """All routes (including inactive) with stops."""
    return [r.detail() for r in network.routes().values()]


def _set_route_stops(route_id: int, stop_ids: list[int]) -> None:
    db = get_db()
    for sid in stop_ids:
        _exists("stops", sid, "Stop")
    db.execute("DELETE FROM route_stops WHERE route_id = ?", (route_id,))
    for seq, sid in enumerate(stop_ids, start=1):
        db.insert("route_stops", {"route_id": route_id, "stop_id": sid, "seq": seq, "chainage_m": 0, "dwell_s": 20})


@api.post("/api/admin/routes", auth=ADMIN, body=RouteIn, tags=T, status=201)
def create_route(ctx):
    """Create a route with ordered stops (first = start, last = end) and optional geometry."""
    b, db = ctx.body, get_db()
    if db.one("SELECT id FROM routes WHERE code = ?", (b.code,)):
        raise ApiError(409, "duplicate", "A route with this code already exists")
    if b.status == "active" and len(b.stop_ids) < 2:
        raise ApiError(422, "too_few_stops", "An active route needs at least 2 stops")
    with db.transaction():
        rid = db.insert("routes", {"code": b.code, "name": b.name, "description": b.description, "color": b.color, "status": b.status,
                                   "avg_speed_kmh": b.avg_speed_kmh, "verified": b.verified, "source": b.source, "is_demo": False,
                                   "shape_json": json.dumps(b.shape or []), "created_at": iso(), "updated_at": iso()})
        _set_route_stops(rid, b.stop_ids)
    rebuild_route_geometry(rid)
    return network.get(rid).detail()


@api.patch("/api/admin/routes/{id:int}", auth=ADMIN, body=RoutePatch, tags=T)
def update_route(ctx):
    """Edit a route: details, status, stop order or geometry."""
    db, rid, b = get_db(), ctx.path["id"], ctx.body
    route = db.one("SELECT * FROM routes WHERE id = ?", (rid,))
    if not route:
        raise not_found("Route")
    vals = {k: v for k, v in b.model_dump(exclude_unset=True, exclude={"stop_ids", "shape"}).items() if v is not None}
    if vals.get("verified") and not (vals.get("source") or route["source"]):
        raise ApiError(422, "source_required", "Verified routes need a source")
    if b.shape is not None:
        vals["shape_json"] = json.dumps(b.shape)
    with db.transaction():
        db.update("routes", rid, {**vals, "updated_at": iso()})
        if b.stop_ids is not None:
            if len(set(b.stop_ids)) != len(b.stop_ids):
                raise ApiError(422, "duplicate_stop", "A stop can only appear once on a route")
            _set_route_stops(rid, b.stop_ids)
    rebuild_route_geometry(rid)
    if b.stop_ids is not None or b.shape is not None or vals.get("status", "active") != "active":
        for bus in db.all("SELECT id FROM buses WHERE route_id = ?", (rid,)):
            t = active_trip(bus["id"])
            if t and (vals.get("status", "active") != "active"):
                end_trip(t["id"], "interrupted", "route_changed")
    if "status" in vals and vals["status"] != route["status"] and vals["status"] == "suspended":
        notify_route_followers(rid, None, "disruption", f"Route {route['code']} suspended",
                               "This route is temporarily suspended.", f"route-suspended:{rid}:{iso()[:16]}")
    return network.get(rid).detail()


@api.delete("/api/admin/routes/{id:int}", auth=ADMIN, tags=T)
def delete_route(ctx):
    """Delete a route (buses on it become unassigned). Blocked while trips are active."""
    db = get_db()
    if db.scalar("SELECT COUNT(*) FROM trips WHERE route_id = ? AND status = 'active'", (ctx.path["id"],)):
        raise ApiError(409, "trips_active", "End the active trips on this route first, or set it to inactive")
    if not db.execute("DELETE FROM routes WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Route")
    network.invalidate()
    return {"ok": True}


# -------------------------------------------------------------- drivers
@api.get("/api/admin/drivers", auth=ADMIN, tags=T)
def admin_drivers(ctx):
    """List drivers with assigned bus and current trip state."""
    rows = get_db().all(
        "SELECT d.id, d.employee_code, d.license_no, d.is_active, d.is_demo, d.location_consent_at, u.id AS user_id, u.name, u.email, "
        "u.phone, u.last_login_at, b.id AS bus_id, b.bus_number, r.code AS route_code FROM drivers d JOIN users u ON u.id = d.user_id "
        "LEFT JOIN buses b ON b.driver_id = d.id LEFT JOIN routes r ON r.id = b.route_id ORDER BY u.name")
    for r in rows:
        r["is_active"], r["is_demo"] = bool(r["is_active"]), bool(r["is_demo"])
        t = active_trip(r["bus_id"]) if r["bus_id"] else None
        r["on_trip"] = bool(t and t["driver_id"] == r["id"])
    return rows


@api.post("/api/admin/drivers", auth=ADMIN, body=DriverIn, tags=T, status=201)
def create_driver(ctx):
    """Create a driver account (and optionally assign a bus)."""
    b, db = ctx.body, get_db()
    if db.one("SELECT id FROM users WHERE phone = ?", (b.phone,)) or (b.email and db.one("SELECT id FROM users WHERE email = ?", (b.email,))):
        raise ApiError(409, "duplicate", "A user with this phone or email already exists")
    if db.one("SELECT id FROM drivers WHERE employee_code = ?", (b.employee_code,)):
        raise ApiError(409, "duplicate", "A driver with this employee code already exists")
    _exists("buses", b.bus_id, "Bus")
    with db.transaction():
        uid = create_user(b.name, b.password, "driver", email=b.email, phone=b.phone)
        did = db.insert("drivers", {"user_id": uid, "employee_code": b.employee_code, "license_no": b.license_no,
                                    "is_active": True, "is_demo": False, "created_at": iso()})
        if b.bus_id:
            if db.one("SELECT driver_id FROM buses WHERE id = ? AND driver_id IS NOT NULL", (b.bus_id,)):
                raise ApiError(409, "bus_taken", "That bus already has a driver")
            db.execute("UPDATE buses SET driver_id = ?, updated_at = ? WHERE id = ?", (did, iso(), b.bus_id))
    return {"id": did, "user_id": uid}


@api.patch("/api/admin/drivers/{id:int}", auth=ADMIN, body=DriverPatch, tags=T)
def update_driver(ctx):
    """Edit a driver, (de)activate the account, assign/unassign a bus, reset password."""
    db, did, b = get_db(), ctx.path["id"], ctx.body
    d = db.one("SELECT * FROM drivers WHERE id = ?", (did,))
    if not d:
        raise not_found("Driver")
    uvals = {}
    if b.name:
        uvals["name"] = b.name
    if b.phone:
        if db.one("SELECT id FROM users WHERE phone = ? AND id <> ?", (b.phone, d["user_id"])):
            raise ApiError(409, "duplicate", "Another user has this phone number")
        uvals["phone"] = b.phone
    if b.new_password:
        uvals["password_hash"] = hash_password(b.new_password)
    if b.is_active is not None:
        uvals["is_active"] = b.is_active
    current_bus = db.one("SELECT id FROM buses WHERE driver_id = ?", (did,))
    t = active_trip(current_bus["id"]) if current_bus else None
    if t and t["driver_id"] == did and (b.is_active is False or b.clear_bus or (b.bus_id and b.bus_id != current_bus["id"])):
        end_trip(t["id"], "interrupted", "driver_reassigned_or_deactivated")
    with db.transaction():
        db.update("users", d["user_id"], uvals)
        dvals = {}
        if b.license_no is not None:
            dvals["license_no"] = b.license_no
        if b.is_active is not None:
            dvals["is_active"] = b.is_active
        db.update("drivers", did, dvals)
        if b.clear_bus or b.bus_id:
            db.execute("UPDATE buses SET driver_id = NULL WHERE driver_id = ?", (did,))
        if b.bus_id:
            _exists("buses", b.bus_id, "Bus")
            other = db.one("SELECT driver_id FROM buses WHERE id = ?", (b.bus_id,))
            if other["driver_id"] and other["driver_id"] != did:
                raise ApiError(409, "bus_taken", "That bus already has a driver; unassign them first")
            db.execute("UPDATE buses SET driver_id = ?, updated_at = ? WHERE id = ?", (did, iso(), b.bus_id))
    return {"ok": True}


# ------------------------------------------------------------ schedules
@api.get("/api/admin/schedules", auth=ADMIN, tags=T)
def admin_schedules(ctx):
    """All timetable entries."""
    rows = get_db().all("SELECT s.*, r.code AS route_code FROM schedules s JOIN routes r ON r.id = s.route_id ORDER BY r.code, s.first_departure")
    for r in rows:
        r["is_demo"] = bool(r["is_demo"])
    return rows


def _schedule_vals(b: ScheduleIn) -> dict:
    _exists("routes", b.route_id, "Route")
    v = b.model_dump()
    v["valid_from"] = b.valid_from.isoformat() if b.valid_from else None
    v["valid_to"] = b.valid_to.isoformat() if b.valid_to else None
    return v


def _notify_schedule_change(route_id: int) -> None:
    r = network.get(route_id)
    if r:
        notify_route_followers(route_id, None, "schedule_change", f"Timetable updated for route {r.code}",
                               "Check the timetable for the new service times.", f"schedule:{route_id}:{iso()[:16]}")


@api.post("/api/admin/schedules", auth=ADMIN, body=ScheduleIn, tags=T, status=201)
def create_schedule(ctx):
    """Add a timetable entry (service days, first/last departure, headway)."""
    db = get_db()
    sid = db.insert("schedules", {**_schedule_vals(ctx.body), "is_demo": False, "created_at": iso(), "updated_at": iso()})
    _notify_schedule_change(ctx.body.route_id)
    return db.one("SELECT * FROM schedules WHERE id = ?", (sid,))


@api.put("/api/admin/schedules/{id:int}", auth=ADMIN, body=ScheduleIn, tags=T)
def update_schedule(ctx):
    """Replace a timetable entry."""
    db = get_db()
    if not db.one("SELECT id FROM schedules WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Schedule")
    db.update("schedules", ctx.path["id"], {**_schedule_vals(ctx.body), "updated_at": iso()})
    _notify_schedule_change(ctx.body.route_id)
    return db.one("SELECT * FROM schedules WHERE id = ?", (ctx.path["id"],))


@api.delete("/api/admin/schedules/{id:int}", auth=ADMIN, tags=T)
def delete_schedule(ctx):
    """Delete a timetable entry."""
    if not get_db().execute("DELETE FROM schedules WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Schedule")
    return {"ok": True}


# --------------------------------------------------------------- alerts
@api.get("/api/admin/alerts", auth=ADMIN, tags=T)
def admin_alerts(ctx):
    """All service alerts."""
    rows = get_db().all("SELECT a.*, r.code AS route_code, s.name AS stop_name FROM service_alerts a LEFT JOIN routes r ON r.id = a.route_id "
                        "LEFT JOIN stops s ON s.id = a.stop_id ORDER BY a.created_at DESC")
    for r in rows:
        r["is_active"] = bool(r["is_active"])
    return rows


@api.post("/api/admin/alerts", auth=ADMIN, body=AlertIn, tags=T, status=201)
def create_alert(ctx):
    """Publish a service alert; followers of the route/stop are notified."""
    b, db = ctx.body, get_db()
    _exists("routes", b.route_id, "Route")
    _exists("stops", b.stop_id, "Stop")
    aid = db.insert("service_alerts", {
        "title": b.title, "body": b.body, "severity": b.severity, "route_id": b.route_id, "stop_id": b.stop_id,
        "starts_at": iso(b.starts_at) if b.starts_at else iso(), "ends_at": iso(b.ends_at) if b.ends_at else None,
        "is_active": True, "created_by": ctx.user_id, "created_at": iso()})
    sent = 0
    if b.notify:
        kind = {"delay": "delay", "schedule_change": "schedule_change"}.get(b.severity, "disruption")
        sent = notify_route_followers(b.route_id, b.stop_id, kind, b.title, b.body or "", f"alert:{aid}")
    alert = db.one("SELECT * FROM service_alerts WHERE id = ?", (aid,))
    hub.publish("public", {"type": "alert", "alert": alert})
    return {**alert, "notified_users": sent}


@api.patch("/api/admin/alerts/{id:int}", auth=ADMIN, body=AlertPatch, tags=T)
def update_alert(ctx):
    """End or edit an alert."""
    db = get_db()
    if not db.one("SELECT id FROM service_alerts WHERE id = ?", (ctx.path["id"],)):
        raise not_found("Alert")
    vals = {k: v for k, v in ctx.body.model_dump(exclude_unset=True).items() if v is not None}
    if "ends_at" in vals:
        vals["ends_at"] = iso(vals["ends_at"])
    db.update("service_alerts", ctx.path["id"], vals)
    return db.one("SELECT * FROM service_alerts WHERE id = ?", (ctx.path["id"],))


# -------------------------------------------------------------- reports
@api.get("/api/admin/reports/daily", auth=ADMIN, query=ReportQ, tags=T)
def report(ctx):
    """Daily operations report (trips, bus activity, route usage, GPS availability, delays, interruptions). format=csv exports trips."""
    day = ctx.query.date or utcnow().astimezone(PK_TZ).date()
    rep = daily_report(day)
    if ctx.query.format == "csv":
        buf = io.StringIO()
        cols = ["trip_id", "bus_number", "route_code", "direction", "source", "status", "started_at", "ended_at", "duration_min",
                "distance_km", "gps_points", "gps_availability_pct", "max_delay_min", "delayed", "offline_events", "end_reason"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rep["trips"])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="speedo-trips-{day.isoformat()}.csv"'})
    return rep


# --------------------------------------------------------------- import
@api.get("/api/admin/import/template.csv", auth=ADMIN, tags=T)
def import_template(ctx):
    """CSV template for importing verified route data."""
    return PlainTextResponse(importer.template_csv(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="speedo-route-import-template.csv"'})


@api.post("/api/admin/import", auth=ADMIN, query=ImportQ, tags=T)
async def import_routes(ctx):
    """Upload a CSV/XLSX of routes and stops (multipart field `file`). Use dry_run=true to validate first."""
    form = await ctx.request.form(max_files=1, max_part_size=5 * 1024 * 1024)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise ApiError(422, "file_required", "Attach a .csv or .xlsx file in the 'file' field")
    content = await upload.read()
    try:
        rows = importer.parse_upload(upload.filename or "", content)
    except ValueError as e:
        raise ApiError(422, "bad_file", str(e))
    except Exception:
        raise ApiError(422, "bad_file", "Could not read this file")
    from starlette.concurrency import run_in_threadpool
    q = ctx.query
    return await run_in_threadpool(importer.import_rows, rows, source=q.source, verified=q.verified, dry_run=q.dry_run)


# ------------------------------------------------------------- settings
@api.get("/api/admin/settings", auth=ADMIN, tags=T)
def admin_settings(ctx):
    """Effective configuration and integration status (read-only; set via environment variables)."""
    db = get_db()
    return {
        "mode": settings.mode, "environment": settings.env, "gps_source": settings.gps_source,
        "database": "postgresql" if settings.is_postgres else "sqlite",
        "postgis": settings.enable_postgis and settings.is_postgres,
        "cache": cache.backend, "push_notifications": "configured" if settings.fcm_configured else "not configured (in-app inbox only)",
        "gps_provider": "configured" if settings.gps_provider_url else "not configured",
        "tracking": {"gps_interval_s": settings.gps_interval_s, "stale_after_s": settings.stale_after_s,
                     "offline_after_s": settings.offline_after_s, "low_accuracy_m": settings.low_accuracy_m,
                     "reject_accuracy_m": settings.reject_accuracy_m, "delay_threshold_min": settings.delay_threshold_min,
                     "gps_retention_days": settings.gps_retention_days},
        "service_area": {"min_lat": settings.area_min_lat, "max_lat": settings.area_max_lat,
                         "min_lon": settings.area_min_lon, "max_lon": settings.area_max_lon},
        "gps_rows_stored": db.scalar("SELECT COUNT(*) FROM gps_locations"),
        "migrations": [r["version"] for r in db.all("SELECT version FROM schema_migrations ORDER BY version")],
    }
