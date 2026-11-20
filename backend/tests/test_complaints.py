"""Driver reporting: passengers complain about a bus/driver by bus number; admins review and reply."""
from datetime import timedelta

from app.models import Bus, Complaint
from app.services.tracking import utcnow

from .conftest import FIRESTORE


def test_categories(client):
    cats = client.get("/api/complaints/categories").json()
    assert {"id": "rash_driving", "label": "Rash / dangerous driving"} in cats


def test_file_check_and_admin_flow(client, passenger_h, admin_h, db):
    # the demo driver's bus; any spelling of the number works
    r = client.post("/api/complaints", headers=passenger_h, json={
        "bus_number": "drv 001", "category": "rash_driving", "description": "Overtook on the wrong side near Liberty.",
        "location": "Liberty Chowk"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["ref_code"].startswith("SPC-") and c["bus_number"] == "DRV-001" and c["status"] == "new"
    assert c["category_label"] == "Rash / dangerous driving" and c["route_code"]
    # passengers never see who the driver is
    assert "driver" not in str(c).lower().replace("rash_driving", "")
    stored = FIRESTORE.data["complaints"][str(db.first(Complaint, ref_code=c["ref_code"]).id)]
    assert stored["driver_id"] is not None  # linked to the bus's driver for the admins

    # status lookup by reference code (no login), case-insensitive
    assert client.get(f"/api/complaints/{c['ref_code'].lower()}").json()["status_label"] == "Received"
    assert client.get("/api/complaints/SPC-NOPE00").status_code == 404
    assert client.get("/api/me/complaints", headers=passenger_h).json()[0]["ref_code"] == c["ref_code"]

    # admin sees it with the driver, replies, passenger gets notified
    rows = client.get("/api/admin/complaints", headers=admin_h).json()
    row = next(x for x in rows if x["ref_code"] == c["ref_code"])
    assert row["driver_name"] == "Demo Driver" and row["contact_name"] == "Demo Passenger"
    up = client.patch(f"/api/admin/complaints/{row['id']}", headers=admin_h,
                      json={"status": "resolved", "admin_note": "Driver warned and retrained."})
    assert up.status_code == 200 and up.json()["status"] == "resolved"
    pub = client.get(f"/api/complaints/{c['ref_code']}").json()
    assert pub["status_label"] == "Resolved" and pub["reply"] == "Driver warned and retrained."
    notes = client.get("/api/me/notifications", headers=passenger_h).json()
    assert any(n["kind"] == "complaint" and c["ref_code"] in n["title"] for n in notes)

    summary = client.get("/api/admin/complaints/summary", headers=admin_h).json()
    assert summary["by_status"]["resolved"] >= 1
    assert any(d["driver_name"] == "Demo Driver" for d in summary["drivers"])
    assert client.get("/api/admin/complaints", params={"status": "resolved"}, headers=admin_h).json()
    assert all(x["status"] in ("new", "in_review") for x in client.get("/api/admin/complaints", headers=admin_h).json())


def test_anonymous_complaint_and_validation(client, db):
    bus = db.first(Bus, bus_number="DEMO-101")
    ok = client.post("/api/complaints", json={"bus_number": "101", "category": "skipped_stop",
                                              "description": "Bus did not stop although I waved.",
                                              "contact_phone": "03001112222"})
    assert ok.status_code == 201 and ok.json()["bus_number"] == bus.bus_number
    bad = [
        {"bus_number": "ZZ-999", "category": "other", "description": "Some long enough text here"},
        {"bus_number": "DEMO-101", "category": "not_a_category", "description": "Some long enough text here"},
        {"bus_number": "DEMO-101", "category": "other", "description": "short"},
        {"bus_number": "DEMO-101", "category": "other", "description": "Some long enough text here",
         "incident_at": (utcnow() + timedelta(days=2)).isoformat()},
    ]
    for body in bad:
        assert client.post("/api/complaints", json=body).status_code == 422, body


def test_complaint_admin_only(client, passenger_h, driver_h):
    for h in (passenger_h, driver_h, {}):
        assert client.get("/api/admin/complaints", headers=h).status_code in (401, 403)
        assert client.patch("/api/admin/complaints/1", headers=h, json={"status": "resolved"}).status_code in (401, 403)
