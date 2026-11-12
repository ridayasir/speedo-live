"""DEMO MODE GPS simulator.

Moves demo buses (is_demo AND gps_device_id starting with 'SIM-') along their routes
and feeds the positions through exactly the same validation/ingestion pipeline a
driver's phone uses. Every simulated bus, route and trip is flagged is_demo and the
UI shows a DEMO badge. The simulator never runs in live mode.

Profiles (from the bus's gps_device_id suffix):
  SIM-NORMAL   typical running speed with stop dwell
  SIM-SLOW     runs slow → shows the "delayed" state
  SIM-DROPOUT  stops sending GPS for 4 minutes every 12 minutes → stale/offline handling
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import random
from dataclasses import dataclass

from ..config import settings
from ..db import get_db, iso, utcnow
from ..errors import ApiError
from .network import network
from .tracking import active_trip, end_trip, ingest_points, scheduled_seconds_to, start_trip

log = logging.getLogger("speedo.sim")
rng = random.Random(42)


@dataclass
class SimBus:
    bus_id: int
    route_id: int
    profile: str
    trip_id: int | None = None
    direction: str = "outbound"
    progress: float = 0.0
    dwell_left: float = 0.0
    layover_left: float = 0.0
    passed_stops: int = 0
    clock: float = 0.0


class Simulator:
    def __init__(self) -> None:
        self.buses: dict[int, SimBus] = {}
        self.started = False

    def setup(self) -> None:
        db = get_db()
        rows = db.all("SELECT * FROM buses WHERE is_demo = ? AND status = 'active' AND gps_device_id LIKE 'SIM-%'", (True,))
        for b in rows:
            route = network.get(b["route_id"])
            if not route or not route.polyline:
                continue
            old = active_trip(b["id"])
            if old:
                end_trip(old["id"], "interrupted", "simulator_restart")
            sb = SimBus(b["id"], route.id, b["gps_device_id"].split("-")[1].upper())
            sb.direction = rng.choice(["outbound", "inbound"])
            sb.progress = rng.uniform(0.05, 0.7) * route.length
            sb.clock = rng.uniform(0, 600)
            self._begin_trip(sb, backdate=True)
            self.buses[b["id"]] = sb
        self.started = True
        log.info("DEMO simulator running %d buses", len(self.buses))

    def _begin_trip(self, sb: SimBus, backdate: bool = False) -> None:
        route = network.get(sb.route_id)
        trip = start_trip(sb.bus_id, None, sb.direction, "simulator")
        sb.trip_id = trip["id"]
        if backdate:
            # a bus placed mid-route "left the terminal" when the timetable says it should have
            behind = scheduled_seconds_to(route, sb.direction, sb.progress) + (420 if sb.profile == "SLOW" else 0)
            get_db().execute("UPDATE trips SET started_at = ? WHERE id = ?", (iso(utcnow() - dt.timedelta(seconds=behind)), trip["id"]))

    def _speed(self, sb: SimBus) -> float:
        route = network.get(sb.route_id)
        base = route.avg_speed_mps * (0.55 if sb.profile == "SLOW" else 1.15)
        wave = 1 + 0.25 * math.sin(sb.clock / 47.0) + rng.uniform(-0.1, 0.1)
        return max(1.0, base * wave)

    def step(self, dt_s: float | None = None) -> None:
        if settings.mode != "demo":
            return
        dt_s = (dt_s or settings.sim_interval_s) * settings.sim_time_scale
        for sb in list(self.buses.values()):
            try:
                self._step_bus(sb, dt_s)
            except Exception:  # never let one bus kill the loop
                log.exception("simulator step failed for bus %s", sb.bus_id)

    def _step_bus(self, sb: SimBus, dt_s: float) -> None:
        route = network.get(sb.route_id)
        if route is None or route.polyline is None:
            return
        sb.clock += dt_s
        if sb.layover_left > 0:
            sb.layover_left -= dt_s
            if sb.layover_left <= 0:
                sb.direction = "inbound" if sb.direction == "outbound" else "outbound"
                sb.progress, sb.passed_stops = 0.0, 0
                self._begin_trip(sb)
            return
        speed = 0.0
        if sb.dwell_left > 0:
            sb.dwell_left -= dt_s
        else:
            speed = self._speed(sb)
            before = sb.progress
            sb.progress = min(route.length, sb.progress + speed * dt_s)
            for s in route.stops:
                sp = s.chainage if sb.direction == "outbound" else route.length - s.chainage
                if before < sp <= sb.progress and 0 < sp < route.length:
                    sb.dwell_left = s.dwell_s
                    sb.progress = sp
                    break
        ch = sb.progress if sb.direction == "outbound" else route.length - sb.progress
        lat, lon, heading = route.polyline.point_at(ch)
        if sb.direction == "inbound":
            heading = (heading + 180) % 360
        # small GPS noise
        lat += rng.gauss(0, 0.00003)
        lon += rng.gauss(0, 0.00003)
        dropout = sb.profile == "DROPOUT" and (sb.clock % 720) > 480
        if not dropout and sb.trip_id:
            point = [{"lat": lat, "lon": lon, "speed_mps": speed, "heading": heading,
                      "accuracy_m": rng.uniform(6, 18), "recorded_at": iso()}]
            try:
                ingest_points(sb.bus_id, sb.trip_id, point, source="simulator")
            except ApiError as e:
                if e.code != "trip_not_active":
                    raise
                # the trip was closed server-side (e.g. no-GPS timeout on a long route): carry on with a fresh trip
                self._begin_trip(sb)
                ingest_points(sb.bus_id, sb.trip_id, point, source="simulator")
        if sb.progress >= route.length - 1 and sb.trip_id:
            end_trip(sb.trip_id, "completed", "reached_terminal")
            sb.trip_id = None
            sb.layover_left = 60


simulator = Simulator()

