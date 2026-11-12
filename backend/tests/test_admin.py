import io
import uuid

from app.db import get_db


def test_admin_endpoints_need_admin_role(client, tokens):
    assert client.get("/api/admin/overview", token="")[0] == 401
    assert client.get("/api/admin/overview", token=tokens["passenger"])[0] == 403
    assert client.get("/api/admin/overview", token=tokens["driver"])[0] == 403
    s, o = client.get("/api/admin/overview", token=tokens["admin"])
    assert s == 200 and o["routes"] == 3 and o["buses_total"] == 8 and o["mode"] == "demo"


def test_fleet_includes_driver_and_gps(client, tokens):
    s, fleet = client.get("/api/admin/fleet", token=tokens["admin"])
    assert s == 200 and len(fleet) == 8
    b103 = next(b for b in fleet if b["bus_number"] == "SP-103")
    assert b103["driver"]["name"] == "Ali Raza"
    assert next(b for b in fleet if b["bus_number"] == "SP-203")["status"] == "out_of_service"


def test_stop_route_bus_driver_schedule_crud(client, tokens):
    A = tokens["admin"]
    tag = uuid.uuid4().hex[:4].upper()
    s, s1 = client.post("/api/admin/stops", {"code": f"T{tag}1", "name": "Test Stop One", "lat": 31.50, "lon": 74.30}, token=A)
    s, s2 = client.post("/api/admin/stops", {"code": f"T{tag}2", "name": "Test Stop Two", "lat": 31.52, "lon": 74.32}, token=A)
    assert s == 201
    assert client.post("/api/admin/stops", {"code": f"T{tag}1", "name": "Dup", "lat": 31.5, "lon": 74.3}, token=A)[0] == 409
    # verified routes must cite a source
    s, d = client.post("/api/admin/routes", {"code": f"R{tag}", "name": "Test Route", "stop_ids": [s1["id"], s2["id"]], "verified": True}, token=A)
    assert s == 422
    s, r = client.post("/api/admin/routes", {"code": f"R{tag}", "name": "Test Route", "stop_ids": [s1["id"], s2["id"]], "color": "#EA580C"}, token=A)
    assert s == 201 and r["stops"][1]["chainage_m"] > 2500 and r["is_demo"] is False
    s, r = client.patch(f"/api/admin/routes/{r['id']}", {"stop_ids": [s2["id"], s1["id"]]}, token=A)
    assert r["stops"][0]["name"] == "Test Stop Two"  # reordered
    assert client.delete(f"/api/admin/stops/{s1['id']}", token=A)[0] == 409  # still used by the route

    s, bus = client.post("/api/admin/buses", {"bus_number": f"TB-{tag}", "route_id": r["id"]}, token=A)
    assert s == 201
    s, drv = client.post("/api/admin/drivers", {"name": "Test Driver", "phone": f"0333{uuid.uuid4().int % 10**7:07d}",
                                                 "password": "drive1234", "employee_code": f"E{tag}", "bus_id": bus["id"]}, token=A)
    assert s == 201
    s, drivers = client.get("/api/admin/drivers", token=A)
    assert next(d for d in drivers if d["id"] == drv["id"])["bus_number"] == f"TB-{tag}"
    # assigning the same driver to another bus is refused
    s, other = client.post("/api/admin/buses", {"bus_number": f"TB2-{tag}"}, token=A)
    s, d = client.patch(f"/api/admin/buses/{other['id']}", {"driver_id": drv["id"]}, token=A)
    assert s == 409 and d["error"]["code"] == "driver_busy"
    # deactivate driver -> cannot log in
    client.patch(f"/api/admin/drivers/{drv['id']}", {"is_active": False}, token=A)
    phone = get_db().one("SELECT u.phone FROM users u JOIN drivers d ON d.user_id = u.id WHERE d.id = ?", (drv["id"],))["phone"]
    s, d = client.post("/api/auth/login", {"identifier": phone, "password": "drive1234"}, token="")
    assert s == 403

    s, sch = client.post("/api/admin/schedules", {"route_id": r["id"], "first_departure": "06:00", "last_departure": "07:00", "headway_min": 20}, token=A)
    assert s == 201
    s, tt = client.get(f"/api/timetable?route_id={r['id']}&date=2026-11-04")
    assert tt["trips_today"] == 4
    assert client.post("/api/admin/schedules", {"route_id": r["id"], "first_departure": "09:00", "last_departure": "08:00", "headway_min": 20}, token=A)[0] == 422
    assert client.put(f"/api/admin/schedules/{sch['id']}", {"route_id": r["id"], "first_departure": "06:00", "last_departure": "06:40", "headway_min": 20}, token=A)[0] == 200
    assert client.delete(f"/api/admin/schedules/{sch['id']}", token=A)[0] == 200

    assert client.delete(f"/api/admin/buses/{other['id']}", token=A)[0] == 200
    assert client.patch(f"/api/admin/routes/{r['id']}", {"status": "inactive"}, token=A)[0] == 200
    assert client.get(f"/api/routes/{r['id']}")[0] == 404  # inactive routes hidden from passengers


def test_bus_deactivation_ends_trip_and_hides_position(client, tokens):
    A = tokens["admin"]
    fleet = client.get("/api/admin/fleet", token=A)[1]
    b = next(x for x in fleet if x["bus_number"] == "SP-301")
    client.patch(f"/api/admin/buses/{b['id']}", {"status": "maintenance"}, token=A)
    pub = client.get(f"/api/buses/{b['id']}")[1]
    assert pub["status"] == "out_of_service" and pub["position"] is None
    client.patch(f"/api/admin/buses/{b['id']}", {"status": "active"}, token=A)


def test_alert_notifies_followers_and_shows_publicly(client, tokens):
    P, A = tokens["passenger"], tokens["admin"]
    assert client.post("/api/me/favorites/routes", {"id": 2}, token=P)[0] == 200
    s, a = client.post("/api/admin/alerts", {"title": "Diversion near Data Darbar", "body": "Road works", "severity": "disruption",
                                             "route_id": 2}, token=A)
    assert s == 201 and a["notified_users"] >= 1
    inbox = client.get("/api/me/notifications", token=P)[1]
    assert inbox["unread"] >= 1 and any(n["title"] == "Diversion near Data Darbar" for n in inbox["items"])
    assert any(x["title"] == "Diversion near Data Darbar" for x in client.get("/api/routes/2")[1]["alerts"])
    client.patch(f"/api/admin/alerts/{a['id']}", {"is_active": False}, token=A)
    assert not any(x["id"] == a["id"] for x in client.get("/api/alerts")[1])


def test_import_dry_run_then_apply(server, client, tokens):
    A = tokens["admin"]
    s, tpl = client.get("/api/admin/import/template.csv", token=A)
    assert s == 200 and tpl.startswith("route_code,route_name")
    good = ("route_code,route_name,route_color,stop_seq,stop_code,stop_name,stop_name_ur,lat,lon,days,first_departure,last_departure,headway_min\n"
            "IMP-1,Imported Route,#123456,1,IMP-A,Imported A,,31.50,74.30,MON,07:00,09:00,30\n"
            "IMP-1,Imported Route,,2,IMP-B,Imported B,,31.51,74.31,,,,\n"
            "IMP-1,Imported Route,,3,IMP-C,Imported C,,31.52,74.33,,,,\n")
    bad = good + "IMP-2,Bad Route,,1,IMP-X,Far away,,24.86,67.0,,,,\n"

    def upload(text, qs):
        boundary = "----speedo" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"routes.csv\"\r\n"
                f"Content-Type: text/csv\r\n\r\n{text}\r\n--{boundary}--\r\n").encode()
        return client.request("POST", f"/api/admin/import?{qs}", raw=body, token=A,
                              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    s, r = upload(bad, "dry_run=true&source=Test+notice")
    assert s == 200 and r["errors"] and not r["applied"]
    s, r = upload(good, "dry_run=true&source=Test+notice")
    assert r["routes"][0]["action"] == "create" and not r["applied"] and not r["errors"]
    s, r = upload(good, "dry_run=false&verified=true&source=Test+notice+2026")
    assert s == 200 and r["applied"], r
    route = next(x for x in client.get("/api/routes")[1] if x["code"] == "IMP-1")
    assert route["verified"] and not route["is_demo"] and route["stop_count"] == 3 and route["source"] == "Test notice 2026"
    assert client.get(f"/api/timetable?route_id={route['id']}&date=2026-11-02")[1]["trips_today"] == 5  # Monday
    s, d = client.request("POST", "/api/admin/import?source=x+y+z", raw=b"", token=A, headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert s == 422


def test_reports_json_and_csv(client, tokens):
    A = tokens["admin"]
    s, rep = client.get("/api/admin/reports/daily", token=A)
    assert s == 200 and rep["summary"]["trips"] >= 1
    assert {"trips", "bus_activity", "route_usage", "delayed_trips", "service_interruptions"} <= set(rep)
    assert any(t["status"] == "interrupted" for t in rep["trips"])
    s, csv_text = client.get("/api/admin/reports/daily?format=csv", token=A)
    assert s == 200 and csv_text.splitlines()[0].startswith("trip_id,bus_number")


def test_settings(client, tokens):
    s, st = client.get("/api/admin/settings", token=tokens["admin"])
    assert s == 200 and st["database"] == "sqlite" and st["migrations"] == ["001_schema", "003_complaints"]
