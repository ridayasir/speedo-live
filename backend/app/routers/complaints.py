"""Driver reporting: passengers complain about a bus or its driver, filed with the bus number.

Anyone (signed in or not) files a complaint and gets a reference code to check its status. The complaint is
linked to the driver on that bus at the time. Administrators review complaints, reply, and see which drivers
and buses receive the most complaints. Passengers never see the driver's identity.
"""
import re
import secrets
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..db import get_db
from ..limits import limiter
from ..models import Bus, Complaint, Driver, Route, User
from ..schemas import COMPLAINT_CATEGORIES, COMPLAINT_STATUSES, ComplaintIn, ComplaintPatch, iso
from ..security import get_current_user, get_optional_user, require_admin
from ..services.accounts import normalize_phone
from ..services.notifications import notify
from ..services.tracking import active_trip, utcnow
from ..store import Session

router = APIRouter(tags=["complaints"])
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
OPEN = ("new", "in_review")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def find_bus(db: Session, number: str) -> Bus:
    """Match what the passenger typed ("sp 101", "SP-101", "101") to one bus."""
    want = _norm(number)
    if not want:
        raise HTTPException(422, "Enter the bus number")
    buses = db.all(Bus)
    hits = [b for b in buses if _norm(b.bus_number) == want]
    if not hits and want.isdigit():
        hits = [b for b in buses if re.search(r"\D" + want + "$", _norm(b.bus_number))]
    if len(hits) != 1:
        raise HTTPException(422, f'No Speedo bus with number "{number}". Check the number painted on the bus (e.g. SP-101).')
    return hits[0]


def _new_ref(db: Session) -> str:
    while True:
        ref = "SPC-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))
        if not db.first(Complaint, ref_code=ref):
            return ref


def _route(db: Session, route_id):
    r = db.get(Route, route_id) if route_id else None
    return {"route_code": r.code if r else None, "route_name": r.name if r else None, "route_color": r.color if r else None}


def public_out(db: Session, c: Complaint) -> dict:
    """What a passenger may see: no driver identity, no admin names."""
    return {
        "ref_code": c.ref_code, "bus_number": c.bus_number, **_route(db, c.route_id), "category": c.category,
        "category_label": COMPLAINT_CATEGORIES.get(c.category, c.category), "description": c.description,
        "location": c.location, "incident_at": iso(c.incident_at), "status": c.status,
        "status_label": COMPLAINT_STATUSES.get(c.status, c.status), "reply": c.admin_note,
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at),
    }


def admin_out(db: Session, c: Complaint) -> dict:
    d = db.get(Driver, c.driver_id) if c.driver_id else None
    filer = db.get(User, c.user_id) if c.user_id else None
    return public_out(db, c) | {
        "id": c.id, "bus_id": c.bus_id, "driver_id": c.driver_id,
        "driver_name": d.user.full_name if d and d.user else None, "driver_code": d.employee_code if d else None,
        "contact_name": c.contact_name, "contact_phone": c.contact_phone,
        "filed_by": {"id": filer.id, "name": filer.full_name, "email": filer.email} if filer else None,
        "admin_note": c.admin_note,
    }


@router.get("/api/complaints/categories")
def categories():
    """Complaint categories passengers can choose from."""
    return [{"id": k, "label": v} for k, v in COMPLAINT_CATEGORIES.items()]


@router.post("/api/complaints", status_code=201)
@limiter.limit("5/minute")
def file_complaint(request: Request, body: ComplaintIn, user: User | None = Depends(get_optional_user),
                   db: Session = Depends(get_db)):
    """Report a bus or its driver. Returns a reference code to check the complaint's status."""
    bus = find_bus(db, body.bus_number)
    trip = active_trip(db, bus.id)
    driver_id = (trip.driver_id if trip else None) or (bus.driver.id if bus.driver else None)
    name, phone = body.contact_name, normalize_phone(body.contact_phone)
    if user:
        name = name or user.full_name
        phone = phone or user.phone
    c = Complaint(ref_code=_new_ref(db), bus_id=bus.id, bus_number=bus.bus_number,
                  route_id=(trip.route_id if trip else None) or bus.route_id, driver_id=driver_id,
                  category=body.category, description=body.description.strip(),
                  location=(body.location or "").strip() or None, incident_at=body.incident_at or utcnow(),
                  user_id=user.id if user else None, contact_name=name, contact_phone=phone, status="new")
    db.add(c)
    db.commit()
    return public_out(db, c)


@router.get("/api/complaints/{ref}")
@limiter.limit("30/minute")
def complaint_status(request: Request, ref: str, db: Session = Depends(get_db)):
    """Check a complaint's status with its reference code."""
    c = db.first(Complaint, ref_code=ref.strip().upper())
    if not c:
        raise HTTPException(404, "No complaint with that reference code")
    return public_out(db, c)


@router.get("/api/me/complaints")
def my_complaints(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Complaints filed while signed in."""
    return [public_out(db, c) for c in db.where(Complaint, user_id=user.id, order_by="created_at", desc=True)]


# --------------------------------------------------------------- admin
@router.get("/api/admin/complaints", dependencies=[Depends(require_admin)])
def admin_complaints(status: str = Query("open", pattern="^(open|all|new|in_review|resolved|rejected)$"),
                     driver_id: int | None = None, bus_id: int | None = None,
                     limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    """Complaints, newest first. status=open means new + under review."""
    filters = []
    if status == "open":
        filters.append(("status", "in", list(OPEN)))
    elif status != "all":
        filters.append(("status", "==", status))
    if driver_id is not None:
        filters.append(("driver_id", "==", driver_id))
    if bus_id is not None:
        filters.append(("bus_id", "==", bus_id))
    rows = db.where(Complaint, *filters, order_by="created_at", desc=True, limit=limit)
    return [admin_out(db, c) for c in rows]


@router.get("/api/admin/complaints/summary", dependencies=[Depends(require_admin)])
def complaints_summary(db: Session = Depends(get_db)):
    """Counts by status, and the drivers and buses with the most complaints in the last 90 days."""
    by_status = Counter(c.status for c in db.where(Complaint))
    recent = db.where(Complaint, ("created_at", ">=", utcnow() - timedelta(days=90)))
    drivers: dict[int, dict] = {}
    for c in recent:
        if not c.driver_id:
            continue
        d = drivers.setdefault(c.driver_id, {"driver_id": c.driver_id, "total": 0, "open": 0, "upheld": 0, "last_at": None})
        d["total"] += 1
        d["open"] += c.status in OPEN
        d["upheld"] += c.status == "resolved"
        d["last_at"] = max(filter(None, [d["last_at"], iso(c.created_at)]))
    for d in drivers.values():
        drv = db.get(Driver, d["driver_id"])
        d["driver_name"] = drv.user.full_name if drv and drv.user else "(removed driver)"
        d["driver_code"] = drv.employee_code if drv else None
    buses = Counter(c.bus_number for c in recent)
    return {
        "by_status": {s: by_status.get(s, 0) for s in COMPLAINT_STATUSES},
        "open": sum(by_status.get(s, 0) for s in OPEN),
        "drivers": sorted(drivers.values(), key=lambda d: (-d["total"], d["last_at"] or ""))[:20],
        "buses": [{"bus_number": b, "total": n} for b, n in buses.most_common(20)],
        "categories": COMPLAINT_CATEGORIES, "statuses": COMPLAINT_STATUSES,
    }


@router.patch("/api/admin/complaints/{complaint_id}")
def update_complaint(complaint_id: int, body: ComplaintPatch, admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Change the status and/or reply to the passenger. A signed-in passenger is notified."""
    c = db.get(Complaint, complaint_id)
    if not c:
        raise HTTPException(404, "Complaint not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "Give a new status or a reply")
    before = (c.status, c.admin_note)
    if "status" in data and data["status"]:
        c.status = data["status"]
    if "admin_note" in data:
        c.admin_note = (data["admin_note"] or "").strip() or None
    c.handled_by = admin.id
    if c.user_id and (c.status, c.admin_note) != before:
        u = db.get(User, c.user_id)
        if u:
            text = f"Bus {c.bus_number} · {COMPLAINT_STATUSES[c.status]}" + (f": {c.admin_note}" if c.admin_note else "")
            notify(db, u, "complaint", f"Complaint {c.ref_code} updated", text[:1000], {"complaint": c.ref_code})
    db.commit()
    return admin_out(db, c)
