"""Passenger complaints about a bus or its driver, filed with the bus number.

Passengers (signed in or not) file a complaint and get a reference code to check its status.
Administrators review complaints, reply, and see which drivers receive the most complaints.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets

from ..db import get_db, iso, utcnow
from ..errors import ApiError, not_found
from ..http import api
from ..schemas import ComplaintIn, ComplaintPatch, ComplaintsQ
from ..services.notify import notify
from ..services.tracking import active_trip

ADMIN = ("admin",)
ANY = ("passenger", "driver", "admin")
CATEGORY_LABELS = {
    "rash_driving": "Rash / dangerous driving", "rude_behaviour": "Rude behaviour", "harassment": "Harassment",
    "overcharging": "Overcharging / fare issue", "skipped_stop": "Didn't stop at the stop", "phone_smoking": "Phone use or smoking while driving",
    "late": "Very late / long wait", "bus_condition": "Bus condition / cleanliness", "other": "Other",
}
STATUS_LABELS = {"new": "Received", "in_review": "Under review", "resolved": "Resolved", "rejected": "Closed"}
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def find_bus(number: str) -> dict:
    """Match what the passenger typed ("sp 101", "SP-101", "101") to a bus."""
    want = _norm(number)
    if not want:
        raise ApiError(422, "unknown_bus", "Enter the bus number")
    buses = get_db().all("SELECT id, bus_number, route_id, driver_id FROM buses")
    exact = [b for b in buses if _norm(b["bus_number"]) == want]
    if not exact and want.isdigit():
        exact = [b for b in buses if re.search(r"\D" + want + "$", _norm(b["bus_number"]))]
    if len(exact) != 1:
        raise ApiError(422, "unknown_bus", f"No Speedo bus with number “{number}”. Check the number painted on the bus (e.g. SP-101).")
    return exact[0]


def _new_ref() -> str:
    db = get_db()
    while True:
        ref = "SPC-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))
        if not db.one("SELECT id FROM complaints WHERE ref_code = ?", (ref,)):
            return ref


def _public(c: dict) -> dict:
    """What a passenger may see about a complaint (no driver identity, no admin names)."""
    return {"ref_code": c["ref_code"], "bus_number": c["bus_number"], "route_code": c.get("route_code"),
            "category": c["category"], "category_label": CATEGORY_LABELS[c["category"]], "description": c["description"],
            "location": c["location"], "incident_at": c["incident_at"], "status": c["status"],
            "status_label": STATUS_LABELS[c["status"]], "reply": c["admin_note"], "created_at": c["created_at"],
            "updated_at": c["updated_at"]}


_SELECT = ("SELECT c.*, r.code AS route_code, r.color AS route_color, u.name AS driver_name, d.employee_code AS driver_code "
           "FROM complaints c LEFT JOIN routes r ON r.id = c.route_id LEFT JOIN drivers d ON d.id = c.driver_id "
           "LEFT JOIN users u ON u.id = d.user_id ")


@api.get("/api/complaints/categories", tags=["complaints"])
def categories(ctx):
    """Complaint categories passengers can choose from."""
    return [{"id": k, "label": v} for k, v in CATEGORY_LABELS.items()]


@api.post("/api/complaints", auth="optional", body=ComplaintIn, tags=["complaints"], rate=5, status=201)
def file_complaint(ctx):
    """File a complaint about a bus or its driver. Returns a reference code to check its status."""
    b, db = ctx.body, get_db()
    bus = find_bus(b.bus_number)
    trip = active_trip(bus["id"])
    driver_id = (trip or {}).get("driver_id") or bus["driver_id"]
    route_id = (trip or {}).get("route_id") or bus["route_id"]
    name, phone = b.contact_name, b.contact_phone
    if ctx.user:
        name = name or ctx.user["name"]
        phone = phone or ctx.user.get("phone")
    now = iso()
    cid = db.insert("complaints", {
        "ref_code": _new_ref(), "bus_id": bus["id"], "bus_number": bus["bus_number"], "route_id": route_id, "driver_id": driver_id,
        "category": b.category, "description": b.description, "location": b.location,
        "incident_at": iso(b.incident_at) if b.incident_at else now,
        "user_id": ctx.user["id"] if ctx.user else None, "contact_name": name, "contact_phone": phone,
        "status": "new", "created_at": now, "updated_at": now})
    return _public(db.one(_SELECT + "WHERE c.id = ?", (cid,)))


@api.get("/api/complaints/{ref}", tags=["complaints"], rate=30)
def complaint_status(ctx):
    """Check a complaint's status with its reference code."""
    c = get_db().one(_SELECT + "WHERE c.ref_code = ?", (ctx.path["ref"].strip().upper(),))
    if not c:
        raise not_found("Complaint")
    return _public(c)


@api.get("/api/me/complaints", auth=ANY, tags=["complaints"])
def my_complaints(ctx):
    """Complaints filed while signed in."""
    return [_public(c) for c in get_db().all(_SELECT + "WHERE c.user_id = ? ORDER BY c.created_at DESC", (ctx.user_id,))]


# --------------------------------------------------------------- admin
@api.get("/api/admin/complaints", auth=ADMIN, query=ComplaintsQ, tags=["admin"])
def admin_complaints(ctx):
    """Complaints, newest first. status=open means new + in review."""
    q = ctx.query
    where, params = [], []
    if q.status == "open":
        where.append("c.status IN ('new','in_review')")
    elif q.status != "all":
        where.append("c.status = ?"); params.append(q.status)
    if q.driver_id is not None:
        where.append("c.driver_id = ?"); params.append(q.driver_id)
    if q.bus_id is not None:
        where.append("c.bus_id = ?"); params.append(q.bus_id)
    sql = _SELECT + (("WHERE " + " AND ".join(where) + " ") if where else "") + "ORDER BY c.created_at DESC LIMIT ?"
    rows = get_db().all(sql, (*params, q.limit))
    for r in rows:
        r["category_label"] = CATEGORY_LABELS[r["category"]]
    return rows


@api.get("/api/admin/complaints/summary", auth=ADMIN, tags=["admin"])
def complaints_summary(ctx):
    """Counts by status, and drivers / buses with the most complaints in the last 90 days."""
    db = get_db()
    since = iso(utcnow() - dt.timedelta(days=90))
    by_status = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM complaints GROUP BY status")}
    drivers = db.all(
        "SELECT c.driver_id, u.name AS driver_name, d.employee_code AS driver_code, COUNT(*) AS total, "
        "SUM(CASE WHEN c.status IN ('new','in_review') THEN 1 ELSE 0 END) AS open, "
        "SUM(CASE WHEN c.status = 'resolved' THEN 1 ELSE 0 END) AS upheld, MAX(c.created_at) AS last_at "
        "FROM complaints c JOIN drivers d ON d.id = c.driver_id JOIN users u ON u.id = d.user_id "
        "WHERE c.created_at >= ? GROUP BY c.driver_id, u.name, d.employee_code ORDER BY total DESC, last_at DESC LIMIT 20", (since,))
    buses = db.all(
        "SELECT c.bus_number, COUNT(*) AS total, SUM(CASE WHEN c.driver_id IS NULL THEN 1 ELSE 0 END) AS no_driver "
        "FROM complaints c WHERE c.created_at >= ? GROUP BY c.bus_number ORDER BY total DESC LIMIT 20", (since,))
    return {"by_status": {s: by_status.get(s, 0) for s in STATUS_LABELS}, "open": by_status.get("new", 0) + by_status.get("in_review", 0),
            "drivers": drivers, "buses": buses, "categories": CATEGORY_LABELS}


@api.patch("/api/admin/complaints/{id:int}", auth=ADMIN, body=ComplaintPatch, tags=["admin"])
def update_complaint(ctx):
    """Change status and/or reply to the passenger. Signed-in passengers are notified."""
    db = get_db()
    c = db.one("SELECT * FROM complaints WHERE id = ?", (ctx.path["id"],))
    if not c:
        raise not_found("Complaint")
    vals = {k: v for k, v in ctx.body.model_dump(exclude_unset=True).items() if v is not None}
    if not vals:
        raise ApiError(422, "nothing_to_change", "Give a new status or a reply")
    vals.update(handled_by=ctx.user_id, updated_at=iso())
    db.update("complaints", c["id"], vals)
    new = db.one(_SELECT + "WHERE c.id = ?", (c["id"],))
    if c["user_id"] and (new["status"] != c["status"] or new["admin_note"] != c["admin_note"]):
        body = f"Bus {new['bus_number']} · {STATUS_LABELS[new['status']]}" + (f" — {new['admin_note']}" if new["admin_note"] else "")
        notify(c["user_id"], "info", f"Complaint {new['ref_code']} updated", body[:1000], {"complaint": new["ref_code"]})
    new["category_label"] = CATEGORY_LABELS[new["category"]]
    return new
