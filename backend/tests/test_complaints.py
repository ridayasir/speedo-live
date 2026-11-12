from app.db import get_db


def _bus():
    return get_db().one("SELECT b.id, b.bus_number, b.driver_id FROM buses b WHERE b.driver_id IS NOT NULL ORDER BY b.id")


def test_file_complaint_anonymously_and_check_status(client):
    bus = _bus()
    typed = bus["bus_number"].lower().replace("-", " ")  # passengers type it loosely
    s, c = client.post("/api/complaints", {"bus_number": typed, "category": "rash_driving",
                                           "description": "Driver was racing another bus near the stop.", "location": "Kalma Chowk"}, token="")
    assert s == 201, c
    assert c["bus_number"] == bus["bus_number"] and c["status"] == "new" and c["ref_code"].startswith("SPC-")
    assert "driver_id" not in c and "contact_phone" not in c  # passengers never see driver identity or contact data
    s, st = client.get(f"/api/complaints/{c['ref_code'].lower()}", token="")
    assert s == 200 and st["status_label"] == "Received"
    row = get_db().one("SELECT driver_id FROM complaints WHERE ref_code = ?", (c["ref_code"],))
    assert row["driver_id"] == bus["driver_id"]  # linked to the driver assigned to that bus


def test_complaint_validation(client):
    assert client.post("/api/complaints", {"bus_number": "XX-999", "category": "late", "description": "Waited for an hour."}, token="")[1]["error"]["code"] == "unknown_bus"
    assert client.post("/api/complaints", {"bus_number": _bus()["bus_number"], "category": "late", "description": "short"}, token="")[0] == 422
    assert client.post("/api/complaints", {"bus_number": _bus()["bus_number"], "category": "nope", "description": "Waited for an hour."}, token="")[0] == 422
    assert client.get("/api/complaints/SPC-NOPE00", token="")[0] == 404


def test_admin_reviews_complaint_and_passenger_is_notified(client, tokens):
    P, A = tokens["passenger"], tokens["admin"]
    bus = _bus()
    s, c = client.post("/api/complaints", {"bus_number": bus["bus_number"], "category": "rude_behaviour",
                                           "description": "Driver shouted at an elderly passenger."}, token=P)
    assert s == 201
    s, mine = client.get("/api/me/complaints", token=P)
    assert s == 200 and any(x["ref_code"] == c["ref_code"] for x in mine)

    assert client.get("/api/admin/complaints", token=P)[0] == 403
    s, rows = client.get("/api/admin/complaints", token=A)
    row = next(r for r in rows if r["ref_code"] == c["ref_code"])
    assert row["driver_name"] and row["contact_name"]
    s, summ = client.get("/api/admin/complaints/summary", token=A)
    assert s == 200 and summ["open"] >= 1 and any(d["driver_id"] == bus["driver_id"] for d in summ["drivers"])
    assert client.get("/api/admin/overview", token=A)[1]["complaints_open"] >= 1

    s, up = client.patch(f"/api/admin/complaints/{row['id']}", {"status": "resolved", "admin_note": "Driver warned."}, token=A)
    assert s == 200 and up["status"] == "resolved"
    s, st = client.get(f"/api/complaints/{c['ref_code']}", token="")
    assert st["status_label"] == "Resolved" and st["reply"] == "Driver warned."
    inbox = client.get("/api/me/notifications", token=P)[1]
    assert any(c["ref_code"] in n["title"] for n in inbox["items"])
