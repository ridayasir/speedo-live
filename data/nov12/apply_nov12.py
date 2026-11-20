"""Load the Speedo network of the 12 Nov version of the app (git commit c229dbd, backend/seed/speedo_network.json).

That network came from the e-Transit route planner (line 42 "LFR- Speedo"): 24 routes, each listed once and run
both ways ("A <-> B"), 498 stops, one timetable per route and 49 simulated buses (SP-101 ...).

    cd backend
    .venv\\Scripts\\python ..\\data\\nov12\\apply_nov12.py

Stop the API first and start it again afterwards. Replaces the routes, stops and demo buses/drivers loaded
earlier (e-Transit S* routes, PMA FRT* routes, earlier sample buses). Sample drivers get Pakistani names; their
passwords go to data/demo/demo_driver_logins.csv (git-ignored).
"""
import csv
import io
import json
import math
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app import firebase  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.demo_fleet import DRIVER_DOMAIN, DRIVER_NAMES, LOGINS, is_sample_driver  # noqa: E402
from app.models import (ArrivalWatch, Bus, BusStop, Driver, FavoriteStop, Journey, Role, Route,  # noqa: E402
                        ServiceAlert)
from app.services import accounts, importer  # noqa: E402
from app.store import store  # noqa: E402

NET = json.loads((HERE / "speedo_network.json").read_text(encoding="utf-8"))
SOURCE = "Speedo Live 12 Nov 2026 network (from PMA e-Transit route planner, line 42 LFR- Speedo)"


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def build_csv() -> tuple[bytes, bytes]:
    stops = {s["code"]: s for s in NET["stops"]}
    out, sch = io.StringIO(), io.StringIO()
    w = csv.writer(out)
    w.writerow(["route_code", "route_name", "sequence", "stop_code", "stop_name", "lat", "lng", "offset_minutes",
                "is_major", "color"])
    ws = csv.writer(sch)
    ws.writerow(["route_code", "days", "first_departure", "last_departure", "frequency_minutes", "notes"])
    for r in NET["routes"]:
        speed = (r.get("avg_speed_kmh") or 18.0) * 1000 / 60  # m per minute
        off, prev = 0.0, None
        for i, code in enumerate(r["stops"]):
            s = stops[code]
            p = (s["lat"], s["lon"])
            if prev:
                off += hav(prev, p) / speed
            prev = p
            w.writerow([r["code"], r["name"], i + 1, code, s["name"], s["lat"], s["lon"], round(off, 1),
                        1 if i in (0, len(r["stops"]) - 1) else 0, r["color"]])
        sc = r.get("schedule") or {}
        if sc:
            ws.writerow([r["code"], sc["days"].lower(), sc["first_departure"], sc["last_departure"],
                         sc.get("headway_min", 15), "Timetable from the 12 Nov app (e-Transit)"])
    return out.getvalue().encode(), sch.getvalue().encode()


def main() -> None:
    firebase.init()
    keep_codes = {s["code"] for s in NET["stops"]}
    new_route_codes = {r["code"] for r in NET["routes"]}
    with SessionLocal() as db:
        # 1. demo buses and drivers of earlier imports
        n_drv = 0
        for d in list(db.all(Driver)):
            u = d.user
            if u and is_sample_driver(u.email):
                firebase.auth_provider.delete_user(u.firebase_uid)
                db.delete(d)
                db.delete(u)
                n_drv += 1
        n_bus = 0
        for b in list(db.all(Bus)):
            if b.is_demo:
                db.delete(b)
                n_bus += 1
        db.commit()
        if LOGINS.exists():
            LOGINS.unlink()
        # 2. routes of earlier imports
        old = [r for r in db.all(Route) if r.code not in new_route_codes]
        for r in old:
            db.delete(r)
        db.commit()
        # 3. stops not in this network: clear references in one pass, then delete in one batch
        gone = [s for s in db.all(BusStop) if s.code not in keep_codes]
        gone_ids = {s.id for s in gone}
        for model in (FavoriteStop, ServiceAlert, ArrivalWatch):
            for x in db.all(model):
                if x.stop_id in gone_ids:
                    db.delete(x)
        for j in db.where(Journey):
            for f in ("from_stop_id", "to_stop_id"):
                if getattr(j, f) in gone_ids:
                    setattr(j, f, None)
        with store.lock:
            store.deleted.extend(gone)
        db.commit()
        print(f"removed {n_bus} demo buses, {n_drv} demo drivers, {len(old)} routes, {len(gone)} stops")

        # 4. routes, stops and timetables
        routes_csv, sched_csv = build_csv()
        rep = importer.import_routes(db, importer.read_table("routes.csv", routes_csv), SOURCE)
        if rep.errors:
            raise SystemExit("route errors: " + "; ".join(rep.errors[:10]))
        srep = importer.import_schedules(db, importer.read_table("schedules.csv", sched_csv))
        if srep.errors:
            raise SystemExit("schedule errors: " + "; ".join(srep.errors[:10]))
        by_code = {r.code: r for r in db.all(Route)}
        for r in NET["routes"]:  # learned average speed from the 12 Nov app
            if r.get("avg_speed_kmh"):
                by_code[r["code"]].avg_speed_kmh = r["avg_speed_kmh"]
        db.commit()
        print({k: v for k, v in rep.__dict__.items() if k != "errors"}, "| timetables:", srep.schedules)

        # 5. the 49 simulated buses
        for b in NET["buses"]:
            route = by_code.get(b["route"])
            if route and not db.first(Bus, bus_number=b["bus_number"]):
                db.add(Bus(bus_number=b["bus_number"], registration_number=f"REG-{b['bus_number']}", capacity=60,
                           route_id=route.id, gps_device_id=b.get("device"), is_demo=True))
        db.commit()

        # 6. one demo driver per route (Pakistani names), on that route's first bus
        LOGINS.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for n, r in enumerate(NET["routes"], 1):
            bus = next((b for b in sorted(db.all(Bus), key=lambda x: x.bus_number) if b.route_id == by_code[r["code"]].id), None)
            name, email, pw = DRIVER_NAMES[(n - 1) % len(DRIVER_NAMES)], f"driver{n:02d}@{DRIVER_DOMAIN}", secrets.token_urlsafe(9)
            user = accounts.create_account(db, name, pw, Role.driver, email=email)
            db.add(Driver(user_id=user.id, license_number=f"LIC-{n:03d}", employee_code=f"SP-DRV-{n:02d}",
                          assigned_bus_id=bus.id if bus else None))
            db.commit()
            rows.append({"driver": name, "login_email": email, "password": pw, "bus": bus.bus_number if bus else "",
                         "route": r["name"]})
        with LOGINS.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"buses: {sum(1 for b in db.all(Bus) if b.is_demo)} | drivers: {len(rows)} (logins in {LOGINS})")


if __name__ == "__main__":
    main()
