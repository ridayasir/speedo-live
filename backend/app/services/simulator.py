"""DEMO MODE bus simulator.

Moves buses that are flagged is_demo along DEMO routes. Every simulated position goes through the
same ingestion path as a driver app, and every bus, route and event it touches carries is_demo=True,
so the apps can show a DEMO badge. It never touches non-demo buses.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Bus, BusStatus, DataSource, Trip, TripStatus
from .geo import point_at_distance
from .tracking import GpsPoint, clear_progress, ingest_points, route_geom, update_route_history, utcnow

log = logging.getLogger("speedo.sim")


@dataclass
class SimBus:
    speed: float  # m/s cruising
    dwell_left: float = 0.0
    last_stop_seq: int = -1


_state: dict[int, SimBus] = {}
_rng = random.Random(42)


def _start_trip(db: Session, bus: Bus, start_m: float = 0.0) -> Trip:
    trip = Trip(bus_id=bus.id, route_id=bus.route_id, status=TripStatus.active, source=DataSource.demo,
                started_at=utcnow(), progress_m=start_m)
    db.add(trip)
    db.flush()
    clear_progress(bus.id)
    return trip


def tick(db: Session, dt: float | None = None) -> int:
    s = get_settings()
    if not s.is_demo:
        return 0
    dt = dt or s.simulator_tick_seconds
    buses = db.execute(
        select(Bus).where(Bus.is_demo.is_(True), Bus.status == BusStatus.active, Bus.route_id.is_not(None))
    ).scalars().all()
    moved = 0
    for bus in buses:
        trip = db.execute(
            select(Trip).where(Trip.bus_id == bus.id, Trip.status == TripStatus.active)
        ).scalars().first()
        geom = route_geom(db, bus.route_id)
        if geom.length_m <= 0:
            continue
        st = _state.get(bus.id)
        if st is None:
            st = _state[bus.id] = SimBus(speed=_rng.uniform(6.0, 10.0))
        if trip is None:
            # stagger demo buses along their route the first time
            start = _rng.uniform(0, geom.length_m * 0.8) if bus.last_gps_at is None else 0.0
            trip = _start_trip(db, bus, start)
            if start:
                # backdate the start so the schedule comparison is fair
                from datetime import timedelta

                trip.started_at = utcnow() - timedelta(minutes=geom.offset_at(start))
        d = trip.progress_m
        if st.last_stop_seq < 0 and d > 0:
            st.last_stop_seq = max((x.sequence for x in geom.stops if x.distance_m <= d), default=-1)
        if st.dwell_left > 0:
            st.dwell_left -= dt
            speed = 0.0
        else:
            # occasional slow-downs to make ETAs and delays visible
            speed = max(0.0, st.speed * _rng.uniform(0.55, 1.15))
            d = min(geom.length_m, d + speed * dt)
            ns = next((x for x in geom.stops if x.sequence > st.last_stop_seq and x.distance_m <= d), None)
            if ns:
                d = ns.distance_m
                st.last_stop_seq = ns.sequence
                st.dwell_left = _rng.uniform(10, 25)
                speed = 0.0
        lat, lng, heading = point_at_distance(geom.path, geom.cum, d)
        trip.progress_m = d  # simulator owns progress exactly
        res = ingest_points(db, trip, [GpsPoint(lat, lng, utcnow(), accuracy_m=8.0, speed_mps=speed, heading=heading)])
        moved += res.accepted
        if d >= geom.length_m - 1 and st.dwell_left <= 0:
            trip.status = TripStatus.completed
            trip.ended_at = utcnow()
            trip.end_reason = "route_end"
            update_route_history(db, trip)
            _state.pop(bus.id, None)
            db.commit()
            _start_trip(db, bus)
            db.commit()
    return moved
