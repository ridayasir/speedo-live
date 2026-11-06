"""Driver app endpoints. A driver can only report the position of the bus assigned to them."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import BusStatus, DataSource, Driver, Trip, TripStatus, User
from ..schemas import GpsBatchIn, TripEndIn, TripStartIn, driver_out, route_out, trip_out
from ..security import require_driver
from ..services.realtime import hub
from ..services.tracking import GpsPoint, active_trip, bus_state, clear_progress, ingest_points, update_route_history, utcnow

router = APIRouter(prefix="/api/driver", tags=["driver"])


def _driver(user: User, db: Session) -> Driver:
    d = db.execute(select(Driver).where(Driver.user_id == user.id)).scalars().first()
    if not d or not d.is_active:
        raise HTTPException(403, "Driver account is not active")
    return d


def _own_trip(db: Session, d: Driver, trip_id: int) -> Trip:
    trip = db.get(Trip, trip_id)
    if not trip or trip.driver_id != d.id:
        raise HTTPException(404, "Trip not found")
    if d.assigned_bus_id != trip.bus_id:
        raise HTTPException(403, "This bus is no longer assigned to you")
    return trip


@router.get("/me")
def me(user: User = Depends(require_driver), db: Session = Depends(get_db)):
    d = _driver(user, db)
    bus = d.assigned_bus
    trip = None
    if bus:
        t = active_trip(db, bus.id)
        trip = trip_out(t) if t and t.driver_id == d.id else None
    return {
        "driver": driver_out(d),
        "bus": {"id": bus.id, "bus_number": bus.bus_number, "status": bus.status.value,
                "registration_number": bus.registration_number} if bus else None,
        "route": route_out(bus.route, detail=True) if bus and bus.route else None,
        "active_trip": trip,
        "bus_state": bus_state(db, bus) if bus else None,
        "gps_interval_seconds": 5,
        "demo_mode": get_settings().is_demo,
    }


@router.post("/trips/start", status_code=201)
def start_trip(body: TripStartIn, user: User = Depends(require_driver), db: Session = Depends(get_db)):
    """Start (or resume) a trip on the assigned bus. Requires explicit location-sharing consent."""
    d = _driver(user, db)
    if not body.consent:
        raise HTTPException(400, "Location sharing consent is required to start a trip")
    bus = d.assigned_bus
    if not bus:
        raise HTTPException(409, "No bus is assigned to you. Contact your administrator.")
    if bus.status != BusStatus.active:
        raise HTTPException(409, f"Bus {bus.bus_number} is {bus.status.value}")
    if not bus.route_id:
        raise HTTPException(409, f"Bus {bus.bus_number} has no route assigned")
    existing = active_trip(db, bus.id)
    if existing:
        if existing.driver_id == d.id:
            return trip_out(existing) | {"resumed": True}
        raise HTTPException(409, "Another trip is already active on this bus")
    d.location_consent_at = utcnow()
    trip = Trip(bus_id=bus.id, route_id=bus.route_id, driver_id=d.id, status=TripStatus.active,
                source=DataSource.driver, started_at=utcnow())
    db.add(trip)
    db.commit()
    clear_progress(bus.id)
    hub.publish({"type": "trip_started", **bus_state(db, bus, trip)})
    return trip_out(trip) | {"resumed": False}


@router.post("/trips/{trip_id}/locations")
def post_locations(trip_id: int, body: GpsBatchIn, user: User = Depends(require_driver), db: Session = Depends(get_db)):
    """Send one or more GPS fixes (buffered fixes from offline periods are accepted up to 1 hour old)."""
    d = _driver(user, db)
    trip = _own_trip(db, d, trip_id)
    if trip.status != TripStatus.active:
        raise HTTPException(409, f"Trip is {trip.status.value}")
    pts = [GpsPoint(p.lat, p.lng, p.recorded_at, p.accuracy_m, p.speed_mps, p.heading) for p in body.points]
    res = ingest_points(db, trip, pts)
    return {"accepted": res.accepted, "stored": res.stored, "duplicates": res.duplicates,
            "rejected": res.rejected, "state": res.state}


@router.post("/trips/{trip_id}/end")
def end_trip(trip_id: int, body: TripEndIn | None = None, user: User = Depends(require_driver),
             db: Session = Depends(get_db)):
    d = _driver(user, db)
    trip = _own_trip(db, d, trip_id)
    if trip.status != TripStatus.active:
        return trip_out(trip)
    trip.status = TripStatus.completed
    trip.ended_at = utcnow()
    trip.end_reason = (body.reason if body else "completed")[:64]
    update_route_history(db, trip)
    db.commit()
    clear_progress(trip.bus_id)
    hub.publish({"type": "trip_ended", **bus_state(db, trip.bus, find_trip=False)})
    return trip_out(trip)


@router.get("/trips")
def trip_history(limit: int = 30, user: User = Depends(require_driver), db: Session = Depends(get_db)):
    d = _driver(user, db)
    rows = db.execute(
        select(Trip).where(Trip.driver_id == d.id).order_by(Trip.started_at.desc()).limit(min(limit, 100))
    ).scalars().all()
    return [trip_out(t) for t in rows]
