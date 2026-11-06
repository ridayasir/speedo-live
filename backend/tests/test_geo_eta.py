"""Unit tests for geometry, validation and ETA maths (no HTTP)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Bus, Route, Trip, TripStatus
from app.services import geo
from app.services.tracking import (
    GpsPoint,
    bus_state,
    gps_freshness,
    live_eta_seconds,
    route_geom,
    utcnow,
    validate_point,
)


def test_haversine_known_distance():
    # ~1 degree latitude ≈ 111 km
    assert geo.haversine_m(31.0, 74.0, 32.0, 74.0) == pytest.approx(111_195, rel=0.01)


def test_projection_onto_path():
    path = [[31.50, 74.30], [31.50, 74.32]]
    p = geo.project_onto_path(31.501, 74.31, path)
    total = geo.haversine_m(31.50, 74.30, 31.50, 74.32)
    assert p.distance_along_m == pytest.approx(total / 2, rel=0.02)
    assert p.offset_m == pytest.approx(111, rel=0.05)


def test_point_at_distance_round_trip():
    path = [[31.50, 74.30], [31.52, 74.30], [31.52, 74.33]]
    cum = geo.cumulative_lengths(path)
    lat, lng, _ = geo.point_at_distance(path, cum, cum[-1] * 0.7)
    assert geo.project_onto_path(lat, lng, path, cum).distance_along_m == pytest.approx(cum[-1] * 0.7, rel=0.01)


@pytest.mark.parametrize("lat,lng,reason", [
    (95, 74.3, "invalid_coordinates"),
    (31.5, 200, "invalid_coordinates"),
    (24.86, 67.0, "outside_service_area"),  # Karachi
    (0, 0, "outside_service_area"),
])
def test_invalid_coordinates_rejected(lat, lng, reason):
    assert validate_point(GpsPoint(lat, lng, utcnow()), utcnow()) == reason


def test_low_accuracy_and_future_timestamps_rejected():
    now = utcnow()
    assert validate_point(GpsPoint(31.5, 74.3, now, accuracy_m=500), now) == "low_accuracy"
    assert validate_point(GpsPoint(31.5, 74.3, now + timedelta(minutes=5)), now) == "timestamp_in_future"
    assert validate_point(GpsPoint(31.5, 74.3, now - timedelta(hours=3)), now) == "timestamp_too_old"
    assert validate_point(GpsPoint(31.5, 74.3, now, accuracy_m=10, speed_mps=8), now) is None


def test_stale_and_offline_detection(db):
    bus = db.execute(select(Bus).where(Bus.bus_number == "DEMO-101")).scalars().one()
    now = utcnow()
    bus.last_gps_at = now - timedelta(seconds=10)
    assert gps_freshness(bus, now) == "fresh"
    bus.last_gps_at = now - timedelta(seconds=120)
    assert gps_freshness(bus, now) == "stale"
    bus.last_gps_at = now - timedelta(seconds=900)
    assert gps_freshness(bus, now) == "offline"
    bus.last_gps_at = None
    assert gps_freshness(bus, now) == "none"
    db.rollback()


def test_stale_is_not_reported_as_stopped(db):
    bus = db.execute(select(Bus).where(Bus.bus_number == "DEMO-102")).scalars().one()
    trip = Trip(bus_id=bus.id, route_id=bus.route_id, status=TripStatus.active, started_at=utcnow())
    db.add(trip)
    db.flush()
    bus.last_lat, bus.last_lng, bus.last_speed_mps = 31.55, 74.32, 0.0
    bus.last_gps_at = utcnow() - timedelta(seconds=120)
    st = bus_state(db, bus, trip)
    assert st["status"] == "stale" and st["motion"] is None  # unknown, not "stopped"
    bus.last_gps_at = utcnow()
    st = bus_state(db, bus, trip)
    assert st["motion"] == "stopped"
    db.rollback()


def test_eta_uses_distance_and_speed(db):
    route = db.execute(select(Route).where(Route.code == "DEMO-1")).scalars().one()
    bus = db.execute(select(Bus).where(Bus.bus_number == "DEMO-103")).scalars().one()
    geom = route_geom(db, route)
    trip = Trip(bus_id=bus.id, route_id=route.id, status=TripStatus.active, started_at=utcnow(), progress_m=0)
    db.add(trip)
    db.flush()
    target = geom.stops[1].distance_m
    secs = live_eta_seconds(db, trip, target)
    # no recent movement -> historical/default 20 km/h
    assert secs == pytest.approx(target / (20 / 3.6), rel=0.01)
    trip.progress_m = target + 200
    assert live_eta_seconds(db, trip, target) is None  # already passed
    db.rollback()
