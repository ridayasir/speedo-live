"""REAL-WORLD MODE integration point for an approved external GPS provider.

No official Speedo/PMA/PTC GPS feed is connected. When an authorised feed becomes available:

1. Implement `fetch_positions()` to return the provider's latest fixes (bus identified by
   `gps_device_id`, which admins set on each bus).
2. Set DATA_SOURCE=provider and the provider's credentials in the environment.
3. The background loop in main.py calls `poll(db)` every few seconds; each fix goes through the same
   validation, storage and broadcast path as driver-app updates (tracking.ingest_points).

Never point this at a private government system without written authorisation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Bus, DataSource, Trip, TripStatus
from .tracking import GpsPoint, ingest_points, utcnow


@dataclass
class ProviderFix:
    device_id: str
    lat: float
    lng: float
    recorded_at: datetime
    speed_mps: float | None = None
    heading: float | None = None
    accuracy_m: float | None = None


class GpsProvider:
    name = "unconfigured"

    def fetch_positions(self) -> list[ProviderFix]:
        """Return the latest fixes from the provider. Not implemented: no authorised feed exists yet."""
        return []


provider = GpsProvider()


def poll(db: Session) -> int:
    count = 0
    for fix in provider.fetch_positions():
        bus = db.execute(select(Bus).where(Bus.gps_device_id == fix.device_id)).scalars().first()
        if not bus or not bus.route_id:
            continue
        trip = db.execute(select(Trip).where(Trip.bus_id == bus.id, Trip.status == TripStatus.active)).scalars().first()
        if trip is None:
            trip = Trip(bus_id=bus.id, route_id=bus.route_id, source=DataSource.provider, started_at=utcnow())
            db.add(trip)
            db.flush()
        res = ingest_points(db, trip, [GpsPoint(fix.lat, fix.lng, fix.recorded_at, fix.accuracy_m, fix.speed_mps, fix.heading)])
        count += res.accepted
    return count
