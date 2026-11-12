"""Driver endpoints: assigned bus/route, consent, trips and GPS sharing."""
from __future__ import annotations

from ..config import settings
from ..db import get_db, iso
from ..errors import ApiError
from ..http import api
from ..schemas import ConsentIn, GpsBatchIn, GpsPointIn, PageQ, TripEndIn, TripStartIn
from ..services.network import network
from ..services.tracking import active_trip, bus_payload, end_trip, ingest_points, start_trip

DRIVER = ("driver",)


def _driver(ctx) -> dict:
    d = get_db().one("SELECT * FROM drivers WHERE user_id = ?", (ctx.user_id,))
    if not d or not d["is_active"]:
        raise ApiError(403, "driver_inactive", "Your driver account is not active")
    return d


def _bus(driver: dict) -> dict:
    bus = get_db().one("SELECT * FROM buses WHERE driver_id = ?", (driver["id"],))
    if not bus:
        raise ApiError(409, "no_bus_assigned", "No bus is assigned to you. Contact your depot administrator.")
    return bus


@api.get("/api/driver/me", auth=DRIVER, tags=["driver"])
def driver_me(ctx):
    """Driver profile, assigned bus and route, current trip."""
    d = _driver(ctx)
    bus = get_db().one("SELECT * FROM buses WHERE driver_id = ?", (d["id"],))
    route = network.get(bus["route_id"]) if bus else None
    trip = active_trip(bus["id"]) if bus else None
    return {
        "driver": {"id": d["id"], "name": ctx.user["name"], "phone": ctx.user["phone"], "email": ctx.user["email"],
                   "employee_code": d["employee_code"], "license_no": d["license_no"], "is_demo": bool(d["is_demo"]),
                   "location_consent_at": d["location_consent_at"]},
        "bus": {"id": bus["id"], "bus_number": bus["bus_number"], "status": bus["status"], "is_demo": bool(bus["is_demo"])} if bus else None,
        "route": route.detail() if route else None,
        "trip": trip,
        "live": bus_payload(bus, trip=trip, with_eta=False) if bus else None,
        "settings": {"gps_interval_s": settings.gps_interval_s, "low_accuracy_m": settings.low_accuracy_m,
                     "reject_accuracy_m": settings.reject_accuracy_m},
    }


@api.post("/api/driver/consent", auth=DRIVER, body=ConsentIn, tags=["driver"])
def consent(ctx):
    """Record (or withdraw) consent to share location while on a trip."""
    d = _driver(ctx)
    if not ctx.body.accepted:
        bus = get_db().one("SELECT id FROM buses WHERE driver_id = ?", (d["id"],))
        trip = active_trip(bus["id"]) if bus else None
        if trip:
            end_trip(trip["id"], "interrupted", "consent_withdrawn")
    get_db().update("drivers", d["id"], {"location_consent_at": iso() if ctx.body.accepted else None})
    return {"location_consent_at": iso() if ctx.body.accepted else None}


@api.post("/api/driver/trips/start", auth=DRIVER, body=TripStartIn, tags=["driver"], status=201)
def trip_start(ctx):
    """Start a trip on the assigned bus. Resumes the existing trip after an app restart."""
    d = _driver(ctx)
    if not d["location_consent_at"]:
        raise ApiError(412, "consent_required", "Accept location sharing before starting a trip")
    bus = _bus(d)
    return start_trip(bus["id"], d["id"], ctx.body.direction, "driver")


@api.post("/api/driver/trips/end", auth=DRIVER, body=TripEndIn, tags=["driver"])
def trip_end(ctx):
    """End the current trip; location sharing stops."""
    d = _driver(ctx)
    bus = _bus(d)
    trip = active_trip(bus["id"])
    if not trip or trip["driver_id"] != d["id"]:
        raise ApiError(409, "no_active_trip", "You have no active trip")
    return end_trip(trip["id"], ctx.body.reason, "ended_by_driver" if ctx.body.reason == "completed" else "driver_reported_interruption")


def _ingest(ctx, points):
    d = _driver(ctx)
    bus = _bus(d)
    trip = active_trip(bus["id"])
    if not trip:
        raise ApiError(409, "no_active_trip", "Start a trip before sharing location")
    if trip["driver_id"] != d["id"]:
        raise ApiError(403, "not_your_trip", "This trip belongs to another driver")
    res = ingest_points(bus["id"], trip["id"], [p.model_dump() for p in points], driver_id=d["id"], source="driver")
    res["trip_id"] = trip["id"]
    return res


@api.post("/api/driver/location", auth=DRIVER, body=GpsPointIn, tags=["driver"], rate=60)
def location(ctx):
    """Send one GPS fix (every ~5–10 s while a trip is active)."""
    return _ingest(ctx, [ctx.body])


@api.post("/api/driver/location/batch", auth=DRIVER, body=GpsBatchIn, tags=["driver"], rate=30)
def location_batch(ctx):
    """Flush fixes queued while offline (max 100, any order; duplicates are ignored)."""
    return _ingest(ctx, ctx.body.points)


@api.get("/api/driver/trips", auth=DRIVER, query=PageQ, tags=["driver"])
def trip_history(ctx):
    """The driver's recent trips."""
    d = _driver(ctx)
    return get_db().all(
        "SELECT t.id, t.direction, t.status, t.started_at, t.ended_at, t.gps_points, t.distance_m, t.max_delay_min, t.offline_events, "
        "t.end_reason, b.bus_number, r.code AS route_code FROM trips t JOIN buses b ON b.id = t.bus_id JOIN routes r ON r.id = t.route_id "
        "WHERE t.driver_id = ? ORDER BY t.started_at DESC LIMIT ?", (d["id"], ctx.query.limit))
