"""Add a DEMO fleet to the real routes: one simulated bus per route and one demo driver per bus.

    python -m app.demo_fleet            add (skips what already exists)
    python -m app.demo_fleet --remove   delete the demo buses and demo drivers again

Everything is clearly labelled: buses are numbered DEMO-<route> with is_demo=True (the apps show a DEMO
badge, and the simulator moves them when DATA_SOURCE=demo); drivers have DEMO licence/employee codes and
@speedolive.demo sign-in addresses. Driver passwords are random and written only to
data/demo/demo_driver_logins.csv on this computer (git-ignored).
"""
import argparse
import csv
import secrets
from pathlib import Path

from . import firebase
from .db import SessionLocal
from .models import Bus, Driver, Role, Route, User
from .services import accounts

DRIVER_NAMES = [
    "Muhammad Imran", "Ali Raza", "Usman Khalid", "Bilal Ahmed", "Asif Mehmood", "Zeeshan Haider",
    "Kashif Iqbal", "Naveed Akhtar", "Shahid Mehmood", "Rizwan Ali", "Faisal Javed", "Tariq Mehmood",
    "Waqas Ahmad", "Adnan Sarwar", "Nadeem Abbas", "Hamza Rafiq", "Sajid Hussain", "Imtiaz Ahmed",
]
LOGINS = Path(__file__).resolve().parents[2] / "data" / "demo" / "demo_driver_logins.csv"


def add(db) -> None:
    routes = sorted((r for r in db.all(Route) if not r.code.endswith("R") and not r.is_demo), key=lambda r: r.code)
    if not routes:
        raise SystemExit("No routes found. Import the routes first.")
    LOGINS.parent.mkdir(parents=True, exist_ok=True)
    new_logins = []
    for n, route in enumerate(routes, 1):
        number = f"DEMO-{route.code}"
        bus = db.first(Bus, bus_number=number)
        if not bus:
            bus = Bus(bus_number=number, registration_number=f"DEMO-REG-{n:03d}", capacity=60, route_id=route.id,
                      is_demo=True)
            db.add(bus)
            db.commit()
        email = f"driver{n:02d}@speedolive.demo"
        if accounts.find_user(email=email):
            continue
        name = DRIVER_NAMES[(n - 1) % len(DRIVER_NAMES)]
        password = secrets.token_urlsafe(9)
        user = accounts.create_account(db, name, password, Role.driver, email=email)
        db.add(Driver(user_id=user.id, license_number=f"DEMO-LIC-{n:03d}", employee_code=f"DEMO-EMP-{n:03d}",
                      assigned_bus_id=bus.id if not bus.driver else None))
        db.commit()
        new_logins.append({"driver": name, "login_email": email, "password": password, "bus": number,
                           "route": f"{route.code}: {route.name.split(': ', 1)[-1]}"})
        print(f"  {number:12} {route.code}  driver: {name} ({email})")
    if new_logins:
        exists = LOGINS.exists()
        with LOGINS.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(new_logins[0].keys()))
            if not exists:
                w.writeheader()
            w.writerows(new_logins)
    print(f"Demo buses: {sum(1 for b in db.all(Bus) if b.is_demo)} | demo drivers added now: {len(new_logins)}")
    print(f"Driver logins saved to {LOGINS}")


def remove(db) -> None:
    for d in list(db.all(Driver)):
        u = d.user
        if d.license_number.startswith("DEMO-LIC-") and u and u.email and u.email.endswith("@speedolive.demo"):
            firebase.auth_provider.delete_user(u.firebase_uid)
            db.delete(d)
            db.delete(u)
    for b in list(db.all(Bus)):
        if b.is_demo and b.bus_number.startswith("DEMO-"):
            db.delete(b)
    db.commit()
    if LOGINS.exists():
        LOGINS.unlink()
    print("Demo buses and drivers removed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    firebase.init()
    with SessionLocal() as db:
        remove(db) if args.remove else add(db)
