"""Add a sample fleet to the real routes: one simulated bus per route and one sample driver per bus.

    python -m app.demo_fleet            add (skips what already exists)
    python -m app.demo_fleet --remove   delete the sample buses and sample drivers again

Buses are numbered SP-001, SP-002 ... and flagged is_demo=True (internally: the simulator moves them when
DATA_SOURCE=demo; the apps show no label). Drivers sign in with driverNN@speedolive.example (".example" can never
be a real mailbox) and have LIC-/SP-DRV- codes. Passwords are random and written only to
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
    "Arshad Mahmood", "Junaid Akram", "Shoaib Anwar", "Irfan Saeed", "Mudassar Hussain", "Qaiser Abbas",
]
LOGINS = Path(__file__).resolve().parents[2] / "data" / "demo" / "demo_driver_logins.csv"
# Sample driver accounts sign in with <name>@speedolive.example (".example" is reserved and can never be a real
# mailbox). Older runs used @speedolive.demo; both are recognised as sample accounts.
DRIVER_DOMAIN = "speedolive.example"


def is_sample_driver(email: str | None) -> bool:
    return bool(email) and email.endswith(("@" + DRIVER_DOMAIN, "@speedolive.demo"))


def add(db) -> None:
    routes = sorted((r for r in db.all(Route) if not r.code.endswith("R") and not r.is_demo), key=lambda r: r.code)
    if not routes:
        raise SystemExit("No routes found. Import the routes first.")
    LOGINS.parent.mkdir(parents=True, exist_ok=True)
    new_logins = []
    for n, route in enumerate(routes, 1):
        number = f"SP-{n:03d}"
        bus = db.first(Bus, bus_number=number)
        if not bus:
            bus = Bus(bus_number=number, registration_number=f"REG-SP-{n:03d}", capacity=60, route_id=route.id,
                      is_demo=True)
            db.add(bus)
            db.commit()
        email = f"driver{n:02d}@{DRIVER_DOMAIN}"
        if accounts.find_user(email=email):
            continue
        name = DRIVER_NAMES[(n - 1) % len(DRIVER_NAMES)]
        password = secrets.token_urlsafe(9)
        user = accounts.create_account(db, name, password, Role.driver, email=email)
        db.add(Driver(user_id=user.id, license_number=f"LIC-{n:03d}", employee_code=f"SP-DRV-{n:02d}",
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
    print(f"Sample buses: {sum(1 for b in db.all(Bus) if b.is_demo)} | sample drivers added now: {len(new_logins)}")
    print(f"Driver logins saved to {LOGINS}")


def remove(db) -> None:
    for d in list(db.all(Driver)):
        u = d.user
        if u and is_sample_driver(u.email):
            firebase.auth_provider.delete_user(u.firebase_uid)
            db.delete(d)
            db.delete(u)
    for b in list(db.all(Bus)):
        if b.is_demo:
            db.delete(b)
    db.commit()
    if LOGINS.exists():
        LOGINS.unlink()
    print("Sample buses and drivers removed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    firebase.init()
    with SessionLocal() as db:
        remove(db) if args.remove else add(db)
