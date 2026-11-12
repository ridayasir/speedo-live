"""Seeding: bootstrap admin (all modes) and clearly-labelled DEMO data (demo mode only)."""
from __future__ import annotations

import json
import logging
import os

from .config import settings
from .db import get_db, iso
from .security import hash_password
from .services.network import rebuild_route_geometry

log = logging.getLogger("speedo.seed")
_SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "seed")
# Real Speedo network imported from e-Transit (seed/import_etransit_speedo.py); falls back to the sample network.
DEMO_FILE = os.environ.get("SPEEDO_SEED_FILE") or next(p for p in (os.path.join(_SEED_DIR, "speedo_network.json"), os.path.join(_SEED_DIR, "demo_network.json"))
                 if os.path.exists(p) or p.endswith("demo_network.json"))
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo@12345")


def create_user(name: str, password: str, role: str, email: str | None = None, phone: str | None = None) -> int:
    db = get_db()
    uid = db.insert("users", {"name": name, "email": email, "phone": phone, "password_hash": hash_password(password),
                              "role": role, "is_active": True, "created_at": iso()})
    if role == "admin":
        db.insert("administrators", {"user_id": uid, "title": "Administrator", "created_at": iso()})
    db.execute("INSERT INTO notification_prefs (user_id) VALUES (?)", (uid,))
    return uid


def bootstrap_admin() -> None:
    db = get_db()
    if db.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin'"):
        return
    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        create_user("Administrator", settings.bootstrap_admin_password, "admin", email=settings.bootstrap_admin_email.lower())
        log.info("created bootstrap admin %s", settings.bootstrap_admin_email)


def seed_demo() -> bool:
    db = get_db()
    if db.scalar("SELECT COUNT(*) FROM routes WHERE is_demo = ?", (True,)):
        return False
    with open(DEMO_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    now = iso()
    with db.transaction():
        stop_ids = {}
        for s in data["stops"]:
            ex = db.one("SELECT id FROM stops WHERE code = ?", (s["code"],))
            stop_ids[s["code"]] = ex["id"] if ex else db.insert("stops", {**s, "is_demo": True, "status": "active", "created_at": now})
        route_ids = {}
        for r in data["routes"]:
            rid = db.insert("routes", {
                "code": r["code"], "name": r["name"], "color": r["color"], "status": "active", "is_demo": True,
                "verified": False, "source": data.get("source", "Speedo Live"), "shape_json": "[]",
                "avg_speed_kmh": r["avg_speed_kmh"], "description": data["_notice"], "created_at": now, "updated_at": now,
            })
            route_ids[r["code"]] = rid
            for seq, code in enumerate(r["stops"], start=1):
                db.insert("route_stops", {"route_id": rid, "stop_id": stop_ids[code], "seq": seq, "chainage_m": 0, "dwell_s": 20})
            db.insert("schedules", {"route_id": rid, **r["schedule"], "notes": "Timetable",
                                    "is_demo": True, "created_at": now, "updated_at": now})
        driver_ids = {}
        for d in data["drivers"]:
            uid = create_user(d["name"], DEMO_PASSWORD, "driver", email=d["email"], phone=d["phone"])
            driver_ids[d["key"]] = db.insert("drivers", {"user_id": uid, "employee_code": d["employee_code"],
                                                         "is_active": True, "is_demo": True, "created_at": now})
        for b in data["buses"]:
            db.insert("buses", {
                "bus_number": b["bus_number"], "route_id": route_ids[b["route"]], "driver_id": driver_ids.get(b.get("driver")),
                "status": b.get("status", "active"), "is_demo": True, "gps_device_id": b["device"], "capacity": 60,
                "created_at": now, "updated_at": now,
            })
        if not db.scalar("SELECT COUNT(*) FROM users WHERE email = ?", ("admin@speedo.demo",)):
            create_user("Speedo Admin", DEMO_PASSWORD, "admin", email="admin@speedo.demo")
        if not db.scalar("SELECT COUNT(*) FROM users WHERE email = ?", ("passenger@speedo.demo",)):
            create_user("Speedo Passenger", DEMO_PASSWORD, "passenger", email="passenger@speedo.demo", phone="03000000009")
    for rid in route_ids.values():
        rebuild_route_geometry(rid)
    log.info("seeded DEMO network: %d routes, %d stops, %d buses", len(route_ids), len(stop_ids), len(data["buses"]))
    return True
