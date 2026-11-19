"""Set up a Speedo Live Firebase project.

Create (or promote) the first administrator. The account is a Firebase Authentication user with an
admin profile in Firestore:

    python -m app.seed --admin-email you@example.com --admin-password "a-long-password" --admin-name "Your Name"

Routes, stops, buses and timetables are NOT created here: load the verified PMA/PTC data through
Admin > Routes > Import CSV / Excel.

`--demo` loads clearly labelled DEMONSTRATION data (sample routes, simulated buses, demo accounts). It is
used by the automated tests; never load it into a project that real passengers use.
"""
import argparse
import os
from datetime import time

from .db import SessionLocal
from .models import Bus, BusStop, Driver, Role, Route, RouteStop, Schedule, ServiceAlert, User
from .services import accounts
from .services.geo import haversine_m
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


def create_admin(db, email: str, password: str | None, name: str) -> User:
    """Create the admin account, or promote an existing account with this email to admin."""
    email = email.strip().lower()
    user = accounts.find_user(email=email)
    if user:
        user.role = Role.admin
        user.is_active = True
        db.commit()
        if password:
            accounts.set_password(user, password)
        return user
    if not password or len(password) < 8:
        raise SystemExit("--admin-password (8+ characters) is required to create a new admin")
    return accounts.create_account(db, name, password, Role.admin, email=email)


def _user(db, email, name, role, password, phone=None):
    u = accounts.find_user(email=email)
    if u:
        return u, False
    return accounts.create_account(db, name, password, role, email=email, phone=phone), True


def seed_demo(db) -> dict:
    """DEMONSTRATION data only (tests). Everything is flagged is_demo and named DEMO."""
    stops = {}
    for code, (name, lat, lng) in STOPS.items():
        s = db.first(BusStop, code=code)
        if not s:
            s = BusStop(code=code, name=name, lat=lat, lng=lng, is_demo=True, source_reference=SOURCE)
            db.add(s)
        stops[code] = s

    routes = {}
    for code, name, color, seq in ROUTES:
        for direction, codes in (("", seq), ("R", list(reversed(seq)))):
            rcode = code + direction
            r = db.first(Route, code=rcode)
            if r:
                routes[rcode] = r
                continue
            parts = name.split(": ", 1)[1].split(" to ")
            rname = name if not direction else f"{name.split(':')[0]} (return): {parts[1]} to {parts[0]}"
            r = Route(code=rcode, name=rname, color=color, is_demo=True, source_reference=SOURCE, fare_pkr=None,
                      path=[[STOPS[c][1], STOPS[c][2]] for c in codes])
            db.add(r)
            for n, (c, off) in enumerate(zip(codes, _offsets(codes))):
                r.stops.append(RouteStop(stop_id=stops[c].id, sequence=n + 1, offset_minutes=off,
                                         is_major=c in MAJOR))
            recompute_route_metrics(db, r)
            db.add(Schedule(route_id=r.id, days="mon,tue,wed,thu,fri,sat", first_departure=time(6, 0),
                            last_departure=time(22, 0), frequency_minutes=12, is_demo=True,
                            notes="Demo timetable, not an official schedule"))
            db.add(Schedule(route_id=r.id, days="sun", first_departure=time(8, 0), last_departure=time(21, 0),
                            frequency_minutes=20, is_demo=True, notes="Demo timetable, not an official schedule"))
            routes[rcode] = r

    n = 101
    buses = []
    for rcode, r in routes.items():
        for _ in range(2):
            num = f"DEMO-{n}"
            b = db.first(Bus, bus_number=num)
            if not b:
                b = Bus(bus_number=num, registration_number=f"DEMO-REG-{n}", capacity=60, route_id=r.id, is_demo=True)
                db.add(b)
            buses.append(b)
            n += 1

    if not db.all(ServiceAlert):
        db.add(ServiceAlert(severity="info", title="Demo mode",
                            message="Speedo Live is running with simulated buses and sample routes. "
                                    "Times and positions are not real."))
    db.commit()

    admin_pw = os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345")
    driver_pw = os.environ.get("SEED_DRIVER_PASSWORD", "Driver@12345")
    pass_pw = os.environ.get("SEED_PASSENGER_PASSWORD", "Passenger@123")
    _user(db, "admin@speedolive.demo", "Demo Administrator", Role.admin, admin_pw)
    du, created = _user(db, "driver@speedolive.demo", "Demo Driver", Role.driver, driver_pw, phone="+923000000001")
    if created:
        # the demo driver gets a separate, non-simulated bus so their own GPS drives it
        bus = Bus(bus_number="DRV-001", registration_number="DEMO-DRV-001", capacity=60, route_id=routes["DEMO-1"].id,
                  is_demo=False)
        db.add(bus)
        db.add(Driver(user_id=du.id, license_number="DEMO-LIC-0001", employee_code="DEMO-EMP-1", assigned_bus_id=bus.id))
    _user(db, "passenger@speedolive.demo", "Demo Passenger", Role.passenger, pass_pw)
    db.commit()
    return {"stops": len(stops), "routes": len(routes), "buses": len(buses)}


seed = seed_demo  # name used by the test suite


if __name__ == "__main__":
    from . import firebase

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--admin-email", default=os.environ.get("SEED_ADMIN_EMAIL"))
    ap.add_argument("--admin-password", default=os.environ.get("SEED_ADMIN_PASSWORD"))
    ap.add_argument("--admin-name", default=os.environ.get("SEED_ADMIN_NAME", "Administrator"))
    ap.add_argument("--demo", action="store_true", help="load DEMONSTRATION data (tests only)")
    ap.add_argument("--ask", action="store_true", help="ask for the admin's email, name and password")
    args = ap.parse_args()
    if args.ask:
        import getpass

        print("Create the Speedo Live administrator account\n")
        args.admin_email = input("Admin email: ").strip()
        args.admin_name = input("Full name: ").strip() or "Administrator"
        while True:
            pw = getpass.getpass("Password (8+ characters, hidden while typing): ")
            if len(pw) < 8:
                print("  Too short, use at least 8 characters.")
            elif pw != getpass.getpass("Type the password again: "):
                print("  The two passwords do not match, try again.")
            else:
                break
        args.admin_password = pw
    if not args.admin_email and not args.demo:
        ap.print_help()
        raise SystemExit(1)
    firebase.init()
    with SessionLocal() as db:
        if args.admin_email:
            u = create_admin(db, args.admin_email, args.admin_password, args.admin_name)
            print(f"Admin ready: {u.email} (user id {u.id}, Firebase uid {u.firebase_uid})")
        if args.demo:
            print(seed_demo(db))
