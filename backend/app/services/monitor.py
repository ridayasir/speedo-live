"""Periodic checks: stale/offline buses, interrupted trips, delay and arrival notifications, retention."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ArrivalWatch, Bus, GpsLocation, Trip, TripStatus, User
from .notifications import notify, notify_route_followers
from .realtime import hub
from .tracking import aware, arrivals_for_stop, bus_state, gps_freshness, utcnow

log = logging.getLogger("speedo.monitor")
_last_gps_state: dict[int, str] = {}


def check_buses(db: Session) -> dict:
    s = get_settings()
    now = utcnow()
    changed = interrupted = 0
    for trip in db.execute(select(Trip).where(Trip.status == TripStatus.active)).scalars().all():
        last = aware(trip.last_update_at) or aware(trip.started_at)
        if (now - last).total_seconds() > s.interrupt_trip_after_seconds:
            trip.status = TripStatus.interrupted
            trip.ended_at = last
            trip.end_reason = "gps_timeout"
            interrupted += 1
    db.commit()
    for bus in db.execute(select(Bus)).scalars().all():
        fresh = gps_freshness(bus, now)
        if _last_gps_state.get(bus.id) != fresh:
            prev = _last_gps_state.get(bus.id)
            _last_gps_state[bus.id] = fresh
            if prev is not None:
                changed += 1
                hub.publish({"type": "bus_status", **bus_state(db, bus, now=now)})
    return {"status_changes": changed, "interrupted": interrupted}


def check_delays(db: Session) -> int:
    s = get_settings()
    sent = 0
    for trip in db.execute(
        select(Trip).where(Trip.status == TripStatus.active, Trip.delay_notified.is_(False))
    ).scalars().all():
        state = bus_state(db, trip.bus, trip)
        if state["status"] == "delayed" and (state["delay_minutes"] or 0) >= s.delay_threshold_minutes:
            label = " (DEMO)" if trip.bus.is_demo else ""
            sent += notify_route_followers(
                db, trip.route_id, "delay", f"Bus {trip.bus.bus_number} is delayed{label}",
                f"Running about {round(state['delay_minutes'])} min behind schedule on {trip.route.name}.",
                dedupe_key=f"delay:{trip.id}",
            )
            trip.delay_notified = True
    db.commit()
    return sent


def check_watches(db: Session) -> int:
    now = utcnow()
    sent = 0
    for w in db.execute(select(ArrivalWatch).where(ArrivalWatch.is_active.is_(True))).scalars().all():
        if w.expires_at and aware(w.expires_at) < now:
            w.is_active = False
            continue
        user = db.get(User, w.user_id)
        arr = arrivals_for_stop(db, w.stop_id, w.route_id, now)
        live = [a for a in arr["live"] if w.bus_id is None or a["bus_id"] == w.bus_id]
        if not live:
            continue
        nxt = live[0]
        demo = " (DEMO)" if nxt["is_demo"] else ""
        if nxt["minutes"] <= 1:
            notify(db, user, "bus_arriving", f"Bus {nxt['bus_number']} is arriving{demo}",
                   f"{nxt['route_name']}: arriving at your stop now.", nxt, dedupe_key=f"arr:{w.id}:{nxt['trip_id']}")
            w.is_active = False
            sent += 1
        elif nxt["minutes"] <= w.minutes_before and not w.notified_approaching:
            notify(db, user, "bus_approaching", f"Bus {nxt['bus_number']} is approaching{demo}",
                   f"About {nxt['minutes']} min away ({nxt['distance_m']} m).", nxt,
                   dedupe_key=f"appr:{w.id}:{nxt['trip_id']}")
            w.notified_approaching = True
            sent += 1
    db.commit()
    return sent


def purge_old_locations(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=get_settings().gps_retention_days)
    res = db.execute(delete(GpsLocation).where(GpsLocation.recorded_at < cutoff))
    db.commit()
    return res.rowcount or 0
