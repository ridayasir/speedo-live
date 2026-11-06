"""Seed DEMONSTRATION data.

Everything created here is flagged is_demo=True and named with a DEMO prefix. These are NOT official
Speedo routes, stops, bus numbers or timetables. Stop names refer to well-known Lahore landmarks with
approximate coordinates so the map looks familiar; route lines are straight segments between stops.
Replace with verified PMA/PTC data through Admin > Import.

Usage:  python -m app.seed            (adds demo data if missing, plus demo accounts)
        python -m app.seed --reset    (drops demo records first)
"""
import argparse
import os
from datetime import time

from sqlalchemy import delete, select

from .db import Base, SessionLocal, engine, is_sqlite
from .models import Administrator, Bus, BusStop, Driver, Role, Route, RouteStop, Schedule, ServiceAlert, User
from .security import hash_password
from .services.geo import haversine_m, point_wkt
from .services.tracking import recompute_route_metrics

SOURCE = "DEMO DATA - not official Speedo information"

# code: (name, lat, lng)  approximate landmark positions
STOPS = {
    "D-SHD": ("Shahdara (Demo)", 31.6230, 74.2900),
    "D-AZC": ("Azadi Chowk (Demo)", 31.5880, 74.3150),
    "D-RLY": ("Railway Station (Demo)", 31.5772, 74.3369),
    "D-DTD": ("Data Darbar (Demo)", 31.5790, 74.3060),
    "D-GPO": ("GPO Chowk (Demo)", 31.5660, 74.3160),
    "D-MZG": ("Mozang Chungi (Demo)", 31.5520, 74.3200),
    "D-SHM": ("Shadman (Demo)", 31.5420, 74.3280),
    "D-JLR": ("Jail Road (Demo)", 31.5380, 74.3370),
    "D-ICH": ("Ichhra (Demo)", 31.5330, 74.3180),
    "D-HFZ": ("Hafeez Centre, Gulberg (Demo)", 31.5160, 74.3430),
    "D-LIB": ("Liberty Market (Demo)", 31.5106, 74.3445),
    "D-KLM": ("Kalma Chowk (Demo)", 31.5050, 74.3310),
    "D-MNM": ("Moon Market, Iqbal Town (Demo)", 31.5100, 74.2880),
    "D-MDT": ("Model Town (Demo)", 31.4836, 74.3220),
    "D-TWN": ("Township (Demo)", 31.4520, 74.3080),
    "D-EMP": ("Johar Town (Demo)", 31.4670, 74.2660),
    "D-WPD": ("Wapda Town (Demo)", 31.4380, 74.2650),
    "D-THK": ("Thokar Niaz Baig (Demo)", 31.4710, 74.2420),
    "D-FRT": ("Fortress Stadium (Demo)", 31.5300, 74.3700),
    "D-DHA": ("DHA Phase 5 (Demo)", 31.4650, 74.4100),
}

ROUTES = [
    ("DEMO-1", "DEMO 1: Railway Station to Thokar Niaz Baig", "#1d4ed8",
     ["D-RLY", "D-GPO", "D-MZG", "D-ICH", "D-MNM", "D-EMP", "D-THK"]),
    ("DEMO-2", "DEMO 2: Shahdara to Liberty Market", "#ea580c",
     ["D-SHD", "D-AZC", "D-RLY", "D-GPO", "D-SHM", "D-JLR", "D-HFZ", "D-LIB"]),
    ("DEMO-3", "DEMO 3: Liberty Market to Wapda Town", "#0f766e",
     ["D-LIB", "D-KLM", "D-MDT", "D-TWN", "D-EMP", "D-WPD"]),
    ("DEMO-4", "DEMO 4: Data Darbar to DHA Phase 5", "#7c3aed",
     ["D-DTD", "D-GPO", "D-JLR", "D-FRT", "D-DHA"]),
]
MAJOR = {"D-RLY", "D-GPO", "D-LIB", "D-THK", "D-SHD", "D-WPD", "D-DHA", "D-DTD", "D-KLM", "D-JLR"}
DEMO_SPEED_KMH = 18.0


def _offsets(codes: list[str]) -> list[float]:
    out, total = [0.0], 0.0
    for a, b in zip(codes, codes[1:]):
        (_, la1, ln1), (_, la2, ln2) = STOPS[a], STOPS[b]
        total += haversine_m(la1, ln1, la2, ln2) / (DEMO_SPEED_KMH * 1000 / 60) + 0.5  # + dwell
        out.append(round(total, 1))
    return out


def reset(db):
    db.execute(delete(Bus).where(Bus.is_demo.is_(True)))
    db.execute(delete(Route).where(Route.is_demo.is_(True)))
    db.execute(delete(BusStop).where(BusStop.is_demo.is_(True)))
    db.commit()


def _user(db, email, name, role, password, phone=None):
    u = db.execute(select(User).where(User.email == email)).scalars().first()
    if u:
        return u, False
    u = User(email=email, full_name=name, role=role, password_hash=hash_password(password), phone=phone)
    db.add(u)
    db.flush()
    return u, True


def seed(db) -> dict:
    stops = {}
    for code, (name, lat, lng) in STOPS.items():
        s = db.execute(select(BusStop).where(BusStop.code == code)).scalars().first()
        if not s:
            s = BusStop(code=code, name=name, lat=lat, lng=lng, geog=point_wkt(lat, lng), is_demo=True,
                        source_reference=SOURCE)
            db.add(s)
        stops[code] = s
    db.flush()

    routes = {}
    for code, name, color, seq in ROUTES:
        for direction, codes in (("", seq), ("R", list(reversed(seq)))):
            rcode = code + direction
            r = db.execute(select(Route).where(Route.code == rcode)).scalars().first()
            if r:
                routes[rcode] = r
                continue
            parts = name.split(": ", 1)[1].split(" to ")
            rname = name if not direction else f"{name.split(':')[0]} (return): {parts[1]} to {parts[0]}"
            r = Route(code=rcode, name=rname, color=color, is_demo=True, source_reference=SOURCE, fare_pkr=None,
                      path=[[STOPS[c][1], STOPS[c][2]] for c in codes])
            db.add(r)
            db.flush()
            for n, (c, off) in enumerate(zip(codes, _offsets(codes))):
                r.stops.append(RouteStop(stop_id=stops[c].id, stop=stops[c], sequence=n + 1, offset_minutes=off,
                                         is_major=c in MAJOR))
            db.flush()
            recompute_route_metrics(db, r)
            db.add(Schedule(route_id=r.id, days="mon,tue,wed,thu,fri,sat", first_departure=time(6, 0),
                            last_departure=time(22, 0), frequency_minutes=12, is_demo=True,
                            notes="Demo timetable, not an official schedule"))
            db.add(Schedule(route_id=r.id, days="sun", first_departure=time(8, 0), last_departure=time(21, 0),
                            frequency_minutes=20, is_demo=True, notes="Demo timetable, not an official schedule"))
            routes[rcode] = r
    db.flush()

    n = 101
    buses = []
    for rcode, r in routes.items():
        for _ in range(2):
            num = f"DEMO-{n}"
            b = db.execute(select(Bus).where(Bus.bus_number == num)).scalars().first()
            if not b:
                b = Bus(bus_number=num, registration_number=f"DEMO-REG-{n}", capacity=60, route_id=r.id, is_demo=True)
                db.add(b)
            buses.append(b)
            n += 1
    db.flush()

    if not db.execute(select(ServiceAlert)).first():
        db.add(ServiceAlert(severity="info", title="Demo mode",
                            message="Speedo Live is running with simulated buses and sample routes. "
                                    "Times and positions are not real."))

    # demo accounts (passwords can be overridden by env vars)
    admin_pw = os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345")
    driver_pw = os.environ.get("SEED_DRIVER_PASSWORD", "Driver@12345")
    pass_pw = os.environ.get("SEED_PASSENGER_PASSWORD", "Passenger@123")
    admin, created = _user(db, "admin@speedolive.demo", "Demo Administrator", Role.admin, admin_pw)
    if created:
        db.add(Administrator(user_id=admin.id))
    du, created = _user(db, "driver@speedolive.demo", "Demo Driver", Role.driver, driver_pw, phone="+923000000001")
    if created:
        # the demo driver gets a separate, non-simulated bus so their own GPS drives it
        bus = Bus(bus_number="DRV-001", registration_number="DEMO-DRV-001", capacity=60, route_id=routes["DEMO-1"].id,
                  is_demo=False)
        db.add(bus)
        db.flush()
        db.add(Driver(user_id=du.id, license_number="DEMO-LIC-0001", employee_code="DEMO-EMP-1", assigned_bus_id=bus.id))
    _user(db, "passenger@speedolive.demo", "Demo Passenger", Role.passenger, pass_pw)
    db.commit()
    return {"stops": len(stops), "routes": len(routes), "buses": len(buses)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if is_sqlite:  # the Alembic migration needs PostGIS
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if args.reset:
            reset(db)
        print(seed(db))
