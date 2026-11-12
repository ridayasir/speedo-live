"""Timetables: service days, departures and scheduled stop times (Asia/Karachi)."""
from __future__ import annotations

import datetime as dt

from ..db import get_db, utcnow
from .network import RouteInfo, network
from .tracking import ordered_stops, scheduled_seconds_to, stop_progress

try:
    from zoneinfo import ZoneInfo
    PK_TZ = ZoneInfo("Asia/Karachi")
except Exception:  # pragma: no cover - tzdata missing
    PK_TZ = dt.timezone(dt.timedelta(hours=5), "PKT")

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _hm(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def schedules_for(route_id: int, day: dt.date) -> list[dict]:
    out = []
    for s in get_db().all("SELECT * FROM schedules WHERE route_id = ? ORDER BY first_departure", (route_id,)):
        days = {d.strip().upper() for d in s["days"].split(",")}
        if DAYS[day.weekday()] not in days:
            continue
        if s["valid_from"] and day < dt.date.fromisoformat(str(s["valid_from"])[:10]):
            continue
        if s["valid_to"] and day > dt.date.fromisoformat(str(s["valid_to"])[:10]):
            continue
        out.append(s)
    return out


def departures(route_id: int, day: dt.date) -> list[dt.datetime]:
    deps: set[dt.datetime] = set()
    for s in schedules_for(route_id, day):
        t = dt.datetime.combine(day, _hm(s["first_departure"]), PK_TZ)
        end = dt.datetime.combine(day, _hm(s["last_departure"]), PK_TZ)
        step = dt.timedelta(minutes=s["headway_min"])
        while t <= end:
            deps.add(t)
            t += step
    return sorted(deps)


def stop_offset_s(route: RouteInfo, direction: str, stop_id: int) -> float | None:
    idx = route.stop_index(stop_id)
    if idx is None:
        return None
    return scheduled_seconds_to(route, direction, stop_progress(route, route.stops[idx], direction))


def next_scheduled_arrivals(route: RouteInfo, stop_id: int, now: dt.datetime | None = None, limit: int = 3) -> list[dict]:
    now = (now or utcnow()).astimezone(PK_TZ)
    out = []
    for direction in ("outbound", "inbound"):
        off = stop_offset_s(route, direction, stop_id)
        if off is None:
            continue
        # skip the terminal a direction ends at (nobody boards there in that direction)
        last = ordered_stops(route, direction)[-1]
        if last.stop_id == stop_id:
            continue
        for day in (now.date(), now.date() + dt.timedelta(days=1)):
            for dep in departures(route.id, day):
                arr = dep + dt.timedelta(seconds=round(off))
                if arr >= now:
                    out.append({"direction": direction, "towards": last.name, "departure": dep.isoformat(),
                                "arrival": arr.isoformat(), "minutes": round((arr - now).total_seconds() / 60)})
                    if len([o for o in out if o["direction"] == direction]) >= limit:
                        break
            if len([o for o in out if o["direction"] == direction]) >= limit:
                break
    return sorted(out, key=lambda o: o["arrival"])[: limit * 2]


def timetable(route_id: int, day: dt.date, stop_id: int | None = None) -> dict | None:
    route = network.get(route_id)
    if not route:
        return None
    scheds = get_db().all("SELECT * FROM schedules WHERE route_id = ? ORDER BY first_departure", (route_id,))
    today = schedules_for(route_id, day)
    deps = departures(route_id, day)
    directions = {}
    for direction in ("outbound", "inbound"):
        stops = ordered_stops(route, direction)
        rows = []
        for s in stops:
            off = scheduled_seconds_to(route, direction, stop_progress(route, s, direction))
            row = {"stop_id": s.stop_id, "name": s.name, "offset_min": round(off / 60, 1)}
            if deps:
                row["first"] = (deps[0] + dt.timedelta(seconds=round(off))).strftime("%H:%M")
                row["last"] = (deps[-1] + dt.timedelta(seconds=round(off))).strftime("%H:%M")
            rows.append(row)
        directions[direction] = {"from": stops[0].name if stops else None, "to": stops[-1].name if stops else None, "stops": rows}
    result = {
        "route": route.summary(),
        "date": day.isoformat(),
        "operates_today": bool(today),
        "schedules": [
            {"id": s["id"], "days": s["days"], "first_departure": s["first_departure"], "last_departure": s["last_departure"],
             "headway_min": s["headway_min"], "valid_from": s["valid_from"], "valid_to": s["valid_to"], "notes": s["notes"],
             "is_demo": bool(s["is_demo"])}
            for s in scheds
        ],
        "first_departure": deps[0].strftime("%H:%M") if deps else None,
        "last_departure": deps[-1].strftime("%H:%M") if deps else None,
        "trips_today": len(deps),
        "directions": directions,
    }
    if stop_id is not None and route.stop_index(stop_id) is not None:
        times = {}
        for direction in ("outbound", "inbound"):
            off = stop_offset_s(route, direction, stop_id)
            times[direction] = [(d + dt.timedelta(seconds=round(off))).strftime("%H:%M") for d in deps]
        result["stop_times"] = {"stop_id": stop_id, **times}
    return result
