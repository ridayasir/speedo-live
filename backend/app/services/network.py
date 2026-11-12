"""Cached view of the route network (routes, ordered stops, geometry, chainages)."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from ..db import get_db, iso
from ..geo import Polyline


@dataclass
class RouteStop:
    stop_id: int
    seq: int
    chainage: float
    dwell_s: int
    code: str
    name: str
    name_ur: str | None
    lat: float
    lon: float


@dataclass
class RouteInfo:
    id: int
    code: str
    name: str
    color: str
    status: str
    is_demo: bool
    verified: bool
    source: str | None
    avg_speed_mps: float
    polyline: Polyline | None
    stops: list[RouteStop]

    @property
    def length(self) -> float:
        return self.polyline.length if self.polyline else 0.0

    def stop_index(self, stop_id: int) -> int | None:
        for i, s in enumerate(self.stops):
            if s.stop_id == stop_id:
                return i
        return None

    def summary(self) -> dict:
        return {
            "id": self.id, "code": self.code, "name": self.name, "color": self.color, "status": self.status,
            "is_demo": self.is_demo, "verified": self.verified, "source": self.source,
            "length_km": round(self.length / 1000, 2), "stop_count": len(self.stops),
            "first_stop": self.stops[0].name if self.stops else None,
            "last_stop": self.stops[-1].name if self.stops else None,
        }

    def detail(self) -> dict:
        d = self.summary()
        d["shape"] = [[round(a, 6), round(o, 6)] for a, o in (self.polyline.points if self.polyline else [])]
        d["stops"] = [
            {"id": s.stop_id, "seq": s.seq, "code": s.code, "name": s.name, "name_ur": s.name_ur,
             "lat": s.lat, "lon": s.lon, "chainage_m": round(s.chainage, 1)}
            for s in self.stops
        ]
        d["avg_speed_kmh"] = round(self.avg_speed_mps * 3.6, 1)
        return d


class Network:
    def __init__(self) -> None:
        self._routes: dict[int, RouteInfo] | None = None
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._routes = None

    def _load(self) -> dict[int, RouteInfo]:
        db = get_db()
        routes: dict[int, RouteInfo] = {}
        rows = db.all("SELECT * FROM routes ORDER BY code")
        stop_rows = db.all(
            "SELECT rs.route_id, rs.stop_id, rs.seq, rs.chainage_m, rs.dwell_s, s.code, s.name, s.name_ur, s.lat, s.lon "
            "FROM route_stops rs JOIN stops s ON s.id = rs.stop_id ORDER BY rs.route_id, rs.seq"
        )
        by_route: dict[int, list[RouteStop]] = {}
        for r in stop_rows:
            by_route.setdefault(r["route_id"], []).append(
                RouteStop(r["stop_id"], r["seq"], r["chainage_m"], r["dwell_s"], r["code"], r["name"], r["name_ur"], r["lat"], r["lon"])
            )
        for r in rows:
            stops = by_route.get(r["id"], [])
            shape = json.loads(r["shape_json"] or "[]")
            pts = shape if len(shape) >= 2 else [(s.lat, s.lon) for s in stops]
            poly = Polyline(pts) if len(pts) >= 2 else None
            routes[r["id"]] = RouteInfo(
                r["id"], r["code"], r["name"], r["color"], r["status"], bool(r["is_demo"]), bool(r["verified"]),
                r["source"], r["avg_speed_kmh"] / 3.6, poly, stops,
            )
        return routes

    def routes(self) -> dict[int, RouteInfo]:
        with self._lock:
            if self._routes is None:
                self._routes = self._load()
            return self._routes

    def get(self, route_id: int | None) -> RouteInfo | None:
        if route_id is None:
            return None
        return self.routes().get(route_id)

    def routes_for_stop(self, stop_id: int) -> list[RouteInfo]:
        return [r for r in self.routes().values() if r.stop_index(stop_id) is not None]


network = Network()


def rebuild_route_geometry(route_id: int) -> None:
    """Recompute stop chainages and route length after stops/shape change."""
    db = get_db()
    route = db.one("SELECT id, shape_json FROM routes WHERE id = ?", (route_id,))
    if not route:
        return
    stops = db.all(
        "SELECT rs.id, s.lat, s.lon FROM route_stops rs JOIN stops s ON s.id = rs.stop_id WHERE rs.route_id = ? ORDER BY rs.seq",
        (route_id,),
    )
    shape = json.loads(route["shape_json"] or "[]")
    pts = shape if len(shape) >= 2 else [(s["lat"], s["lon"]) for s in stops]
    if len(pts) < 2:
        db.update("routes", route_id, {"length_m": 0, "updated_at": iso()})
        network.invalidate()
        return
    poly = Polyline(pts)
    last = 0.0
    for s in stops:
        ch = poly.project(s["lat"], s["lon"], near_chainage=last).chainage
        last = max(last, ch)
        db.execute("UPDATE route_stops SET chainage_m = ? WHERE id = ?", (last, s["id"]))
    db.update("routes", route_id, {"length_m": poly.length, "updated_at": iso()})
    network.invalidate()
