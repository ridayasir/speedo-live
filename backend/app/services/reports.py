"""Operational reports for the admin dashboard (one local day at a time)."""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..db import get_db, iso, parse_ts, utcnow
from .schedule import PK_TZ


def _day_window(day: dt.date) -> tuple[str, str]:
    start = dt.datetime.combine(day, dt.time(0, 0), PK_TZ)
    return iso(start), iso(start + dt.timedelta(days=1))


def daily_report(day: dt.date) -> dict:
    db = get_db()
    a, b = _day_window(day)
    now = utcnow()
    trips = db.all(
        "SELECT t.*, bu.bus_number, r.code AS route_code FROM trips t JOIN buses bu ON bu.id = t.bus_id "
        "JOIN routes r ON r.id = t.route_id WHERE t.started_at >= ? AND t.started_at < ? ORDER BY t.started_at",
        (a, b),
    )
    rows = []
    for t in trips:
        end = parse_ts(t["ended_at"]) or now
        dur = max(1.0, (end - parse_ts(t["started_at"])).total_seconds())
        avail = max(0.0, min(1.0, 1 - t["gps_gap_s"] / dur)) if t["gps_points"] else 0.0
        rows.append({
            "trip_id": t["id"], "bus_number": t["bus_number"], "route_code": t["route_code"], "direction": t["direction"],
            "source": t["source"], "status": t["status"], "started_at": t["started_at"], "ended_at": t["ended_at"],
            "duration_min": round(dur / 60, 1), "distance_km": round(t["distance_m"] / 1000, 2), "gps_points": t["gps_points"],
            "gps_availability_pct": round(avail * 100, 1), "max_delay_min": round(t["max_delay_min"], 1),
            "delayed": t["max_delay_min"] >= settings.delay_threshold_min, "offline_events": t["offline_events"],
            "end_reason": t["end_reason"],
        })
    buses: dict[str, dict] = {}
    for r in rows:
        x = buses.setdefault(r["bus_number"], {"bus_number": r["bus_number"], "trips": 0, "active_min": 0.0, "distance_km": 0.0, "gps_points": 0})
        x["trips"] += 1; x["active_min"] += r["duration_min"]; x["distance_km"] += r["distance_km"]; x["gps_points"] += r["gps_points"]
    usage = {u["route_id"]: u for u in db.all(
        "SELECT route_id, SUM(CASE WHEN event = 'planned' THEN 1 ELSE 0 END) AS planned, "
        "SUM(CASE WHEN event = 'tracked' THEN 1 ELSE 0 END) AS tracked, SUM(CASE WHEN event = 'viewed' THEN 1 ELSE 0 END) AS viewed "
        "FROM route_usage WHERE created_at >= ? AND created_at < ? GROUP BY route_id", (a, b))}
    routes = []
    for r in db.all("SELECT id, code, name, is_demo FROM routes ORDER BY code"):
        rt = [t for t in rows if t["route_code"] == r["code"]]
        u = usage.get(r["id"], {})
        routes.append({"route_code": r["code"], "route_name": r["name"], "is_demo": bool(r["is_demo"]), "trips": len(rt),
                       "delayed_trips": sum(1 for t in rt if t["delayed"]),
                       "journey_plans": int(u.get("planned") or 0), "tracking_views": int(u.get("tracked") or 0) + int(u.get("viewed") or 0)})
    alerts = db.all("SELECT id, title, severity, route_id, starts_at, ends_at FROM service_alerts WHERE starts_at < ? AND (ends_at IS NULL OR ends_at >= ?)", (b, a))
    interrupted = [t for t in rows if t["status"] == "interrupted"]
    avail = [t["gps_availability_pct"] for t in rows if t["gps_points"]]
    return {
        "date": day.isoformat(),
        "summary": {
            "trips": len(rows), "completed": sum(1 for t in rows if t["status"] == "completed"),
            "active": sum(1 for t in rows if t["status"] == "active"), "interrupted": len(interrupted),
            "delayed_trips": sum(1 for t in rows if t["delayed"]),
            "avg_gps_availability_pct": round(sum(avail) / len(avail), 1) if avail else None,
            "offline_events": sum(t["offline_events"] for t in rows), "service_alerts": len(alerts),
        },
        "trips": rows,
        "bus_activity": [{**v, "active_min": round(v["active_min"], 1), "distance_km": round(v["distance_km"], 2)} for v in buses.values()],
        "route_usage": routes,
        "delayed_trips": [t for t in rows if t["delayed"]],
        "service_interruptions": {"alerts": alerts, "interrupted_trips": interrupted},
    }
