"""Admin import of verified route data from CSV or Excel.

One row per stop on a route (see GET /api/admin/import/template.csv):

route_code, route_name, route_color, stop_seq, stop_code, stop_name, stop_name_ur,
lat, lon, days, first_departure, last_departure, headway_min

Schedule columns are optional and read from the route's first row.
"""
from __future__ import annotations

import csv
import io
import re

from ..config import settings
from ..db import get_db, iso
from ..geo import in_service_area
from .network import rebuild_route_geometry

TEMPLATE_HEADER = ["route_code", "route_name", "route_color", "stop_seq", "stop_code", "stop_name", "stop_name_ur",
                   "lat", "lon", "days", "first_departure", "last_departure", "headway_min"]
REQUIRED = ["route_code", "route_name", "stop_seq", "stop_code", "stop_name", "lat", "lon"]
HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_upload(filename: str, content: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        return [{header[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(header)} for r in rows[1:]
                if any(v not in (None, "") for v in r)]
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]
    raise ValueError("Upload a .csv or .xlsx file")


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    w.writerow(["R-EXAMPLE", "Example route name from the official notice", "#1D4ED8", 1, "STOP-A", "First stop name", "",
                "31.5000", "74.3000", "MON,TUE,WED,THU,FRI,SAT,SUN", "06:30", "22:00", 10])
    w.writerow(["R-EXAMPLE", "Example route name from the official notice", "", 2, "STOP-B", "Second stop name", "",
                "31.5100", "74.3100", "", "", "", ""])
    return buf.getvalue()


def import_rows(rows: list[dict], *, source: str, verified: bool, dry_run: bool = True) -> dict:
    errors: list[dict] = []
    routes: dict[str, dict] = {}
    for i, row in enumerate(rows, start=2):  # header is line 1
        missing = [c for c in REQUIRED if not row.get(c)]
        if missing:
            errors.append({"row": i, "message": f"missing {', '.join(missing)}"}); continue
        try:
            lat, lon, seq = float(row["lat"]), float(row["lon"]), int(float(row["stop_seq"]))
        except ValueError:
            errors.append({"row": i, "message": "lat, lon and stop_seq must be numbers"}); continue
        if not in_service_area(lat, lon, settings):
            errors.append({"row": i, "message": f"stop {row['stop_code']} ({lat}, {lon}) is outside the Lahore service area"}); continue
        r = routes.setdefault(row["route_code"], {"code": row["route_code"], "name": row["route_name"],
                                                 "color": row.get("route_color") or "#1D4ED8", "stops": [], "schedule": None})
        if row.get("first_departure"):
            fd, ld = row.get("first_departure", ""), row.get("last_departure", "")
            if not (HM.match(fd) and HM.match(ld)) or not str(row.get("headway_min", "")).strip():
                errors.append({"row": i, "message": "schedule needs first_departure/last_departure as HH:MM and headway_min"})
            else:
                r["schedule"] = {"days": (row.get("days") or "MON,TUE,WED,THU,FRI,SAT,SUN").upper().replace(" ", ""),
                                 "first_departure": fd, "last_departure": ld, "headway_min": int(float(row["headway_min"]))}
        r["stops"].append({"seq": seq, "code": row["stop_code"], "name": row["stop_name"],
                           "name_ur": row.get("stop_name_ur") or None, "lat": lat, "lon": lon, "row": i})
    for r in routes.values():
        seqs = [s["seq"] for s in r["stops"]]
        if len(set(seqs)) != len(seqs):
            errors.append({"row": None, "message": f"route {r['code']}: duplicate stop_seq"})
        codes = [s["code"] for s in r["stops"]]
        if len(set(codes)) != len(codes):
            errors.append({"row": None, "message": f"route {r['code']}: a stop appears twice"})
        if len(r["stops"]) < 2:
            errors.append({"row": None, "message": f"route {r['code']}: needs at least 2 stops"})
        r["stops"].sort(key=lambda s: s["seq"])
    db = get_db()
    summary = []
    for r in routes.values():
        exists = db.one("SELECT id FROM routes WHERE code = ?", (r["code"],))
        summary.append({"code": r["code"], "name": r["name"], "stops": len(r["stops"]),
                        "action": "update" if exists else "create", "schedule": r["schedule"]})
    result = {"dry_run": dry_run, "routes": summary, "errors": errors, "rows": len(rows)}
    if dry_run or errors or not routes:
        result["applied"] = False
        return result

    now = iso()
    with db.transaction():
        for r in routes.values():
            stop_ids = []
            for s in r["stops"]:
                ex = db.one("SELECT id FROM stops WHERE code = ?", (s["code"],))
                if ex:
                    db.update("stops", ex["id"], {"name": s["name"], "name_ur": s["name_ur"], "lat": s["lat"], "lon": s["lon"], "is_demo": False})
                    stop_ids.append(ex["id"])
                else:
                    stop_ids.append(db.insert("stops", {"code": s["code"], "name": s["name"], "name_ur": s["name_ur"],
                                                        "lat": s["lat"], "lon": s["lon"], "is_demo": False, "status": "active", "created_at": now}))
            ex = db.one("SELECT id FROM routes WHERE code = ?", (r["code"],))
            vals = {"name": r["name"], "color": r["color"], "is_demo": False, "verified": verified, "source": source,
                    "shape_json": "[]", "updated_at": now}
            if ex:
                route_id = ex["id"]
                db.update("routes", route_id, vals)
                db.execute("DELETE FROM route_stops WHERE route_id = ?", (route_id,))
            else:
                route_id = db.insert("routes", {"code": r["code"], "status": "active", "created_at": now, **vals})
            for seq, sid in enumerate(stop_ids, start=1):
                db.insert("route_stops", {"route_id": route_id, "stop_id": sid, "seq": seq, "chainage_m": 0, "dwell_s": 20})
            if r["schedule"]:
                db.execute("DELETE FROM schedules WHERE route_id = ?", (route_id,))
                db.insert("schedules", {"route_id": route_id, **r["schedule"], "notes": f"Imported: {source}",
                                        "is_demo": False, "created_at": now, "updated_at": now})
            r["id"] = route_id
    for r in routes.values():
        rebuild_route_geometry(r["id"])
    result["applied"] = True
    return result
