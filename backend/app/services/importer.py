"""Import verified route data from CSV or Excel.

routes file columns (one row per stop, in order):
    route_code, route_name, sequence, stop_code, stop_name, lat, lng, offset_minutes, [is_major], [color], [stop_name_ur]
schedules file columns:
    route_code, days, first_departure, last_departure, frequency_minutes, [notes]
optional shapes file columns (road geometry):
    route_code, sequence, lat, lng

Importing a route replaces its stop list (stops themselves are matched by stop_code and updated).
Each import must name its source (e.g. "PMA route list, Oct 2026") which is stored on every record.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BusStop, Route, RouteStatus, RouteStop, Schedule
from .geo import point_wkt
from .tracking import recompute_route_metrics


@dataclass
class ImportReport:
    routes_created: int = 0
    routes_updated: int = 0
    stops_created: int = 0
    stops_updated: int = 0
    schedules: int = 0
    errors: list[str] = field(default_factory=list)


def read_table(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        return [{head[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(head)} for r in rows[1:]
                if any(v not in (None, "") for v in r)]
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]


def _time(v: str) -> time:
    v = v.strip()
    parts = v.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def import_routes(db: Session, rows: list[dict], source: str, shapes: list[dict] | None = None,
                  is_demo: bool = False) -> ImportReport:
    rep = ImportReport()
    required = {"route_code", "route_name", "sequence", "stop_code", "stop_name", "lat", "lng"}
    if rows and not required.issubset(rows[0].keys()):
        rep.errors.append(f"Missing columns: {', '.join(sorted(required - set(rows[0].keys())))}")
        return rep
    by_route: dict[str, list[dict]] = {}
    for i, r in enumerate(rows, start=2):
        try:
            r["_seq"] = int(float(r["sequence"]))
            r["_lat"], r["_lng"] = float(r["lat"]), float(r["lng"])
            if not (-90 <= r["_lat"] <= 90 and -180 <= r["_lng"] <= 180):
                raise ValueError("coordinates out of range")
            r["_off"] = float(r.get("offset_minutes") or 0)
        except (ValueError, KeyError) as exc:
            rep.errors.append(f"Row {i}: {exc}")
            continue
        by_route.setdefault(r["route_code"], []).append(r)
    if rep.errors:
        return rep

    shape_by_route: dict[str, list[list[float]]] = {}
    for s in shapes or []:
        try:
            shape_by_route.setdefault(s["route_code"], []).append((int(float(s["sequence"])), float(s["lat"]), float(s["lng"])))
        except (ValueError, KeyError) as exc:
            rep.errors.append(f"Shape row: {exc}")
    shape_paths = {k: [[la, ln] for _, la, ln in sorted(v)] for k, v in shape_by_route.items()}

    for code, stops in by_route.items():
        stops.sort(key=lambda x: x["_seq"])
        route = db.execute(select(Route).where(Route.code == code)).scalars().first()
        if route is None:
            route = Route(code=code, name=stops[0]["route_name"], status=RouteStatus.active, is_demo=is_demo)
            db.add(route)
            rep.routes_created += 1
        else:
            rep.routes_updated += 1
            route.stops.clear()
            db.flush()
        route.name = stops[0]["route_name"]
        route.source_reference = source
        route.is_demo = is_demo
        if stops[0].get("color"):
            route.color = stops[0]["color"]
        route.path = shape_paths.get(code) or []
        for n, r in enumerate(stops):
            stop = db.execute(select(BusStop).where(BusStop.code == r["stop_code"])).scalars().first()
            if stop is None:
                stop = BusStop(code=r["stop_code"], name=r["stop_name"], lat=r["_lat"], lng=r["_lng"], is_demo=is_demo)
                db.add(stop)
                rep.stops_created += 1
            else:
                rep.stops_updated += 1
            stop.name, stop.lat, stop.lng = r["stop_name"], r["_lat"], r["_lng"]
            stop.geog = point_wkt(r["_lat"], r["_lng"])
            stop.source_reference = source
            stop.is_demo = is_demo
            if r.get("stop_name_ur"):
                stop.name_ur = r["stop_name_ur"]
            db.flush()
            major = str(r.get("is_major", "")).lower() in ("1", "true", "yes", "y")
            route.stops.append(RouteStop(stop_id=stop.id, sequence=n + 1, offset_minutes=r["_off"], is_major=major,
                                         stop=stop))
        db.flush()
        recompute_route_metrics(db, route)
    db.commit()
    return rep


def import_schedules(db: Session, rows: list[dict], is_demo: bool = False) -> ImportReport:
    rep = ImportReport()
    touched: set[int] = set()
    for i, r in enumerate(rows, start=2):
        route = db.execute(select(Route).where(Route.code == r.get("route_code", ""))).scalars().first()
        if not route:
            rep.errors.append(f"Row {i}: unknown route_code {r.get('route_code')!r}")
            continue
        try:
            first, last = _time(r["first_departure"]), _time(r["last_departure"])
            freq = int(float(r.get("frequency_minutes") or 15))
        except (ValueError, KeyError) as exc:
            rep.errors.append(f"Row {i}: {exc}")
            continue
        if route.id not in touched:  # an import replaces the route's schedules
            for s in list(route.schedules):
                db.delete(s)
            touched.add(route.id)
        days = (r.get("days") or "mon,tue,wed,thu,fri,sat,sun").lower().replace(" ", "")
        db.add(Schedule(route_id=route.id, days=days, first_departure=first, last_departure=last,
                        frequency_minutes=freq, notes=r.get("notes") or None, is_demo=is_demo))
        rep.schedules += 1
    if rep.errors:
        db.rollback()
        return rep
    db.commit()
    return rep
