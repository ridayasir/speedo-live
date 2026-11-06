"""Integration tests through the HTTP API."""
import io
import json
from datetime import timedelta

from sqlalchemy import select

from app.models import Bus, Notification, Trip, TripStatus, User
from app.services import geo, monitor, simulator
from app.services.tracking import route_geom, utcnow

from .conftest import login


# ----------------------------------------------------------------- accounts
def test_register_login_logout(client):
    r = client.post("/api/auth/register", json={"full_name": "Ayesha Khan", "phone": "03001234567", "password": "secret123"})
    assert r.status_code == 201, r.text
    assert r.json()["user"]["phone"] == "+923001234567"
    assert r.json()["user"]["role"] == "passenger"
    h = login(client, "03001234567", "secret123")
    assert client.get("/api/auth/me", headers=h).json()["full_name"] == "Ayesha Khan"
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    # duplicate
    r = client.post("/api/auth/register", json={"full_name": "X Y", "phone": "+923001234567", "password": "secret123"})
    assert r.status_code == 409


def test_register_requires_contact_and_password_rules(client):
    assert client.post("/api/auth/register", json={"full_name": "No Contact", "password": "secret123"}).status_code == 422
    assert client.post("/api/auth/register", json={"full_name": "Shorty", "email": "s@x.pk", "password": "1"}).status_code == 422


def test_wrong_password(client):
    r = client.post("/api/auth/login", json={"identifier": "admin@speedolive.demo", "password": "nope"})
    assert r.status_code == 401


def test_password_is_hashed(db):
    u = db.execute(select(User).where(User.email == "admin@speedolive.demo")).scalars().one()
    assert u.password_hash.startswith("$2") and "Admin" not in u.password_hash


# ----------------------------------------------------------------- discovery
def test_route_and_stop_search(client):
    routes = client.get("/api/routes", params={"q": "Thokar"}).json()
    assert routes and all(r["is_demo"] for r in routes)
    stops = client.get("/api/stops", params={"q": "liberty"}).json()
    assert stops[0]["name"].startswith("Liberty Market")
    near = client.get("/api/stops/nearby", params={"lat": 31.5106, "lng": 74.3445, "radius_m": 500}).json()
    assert near[0]["code"] == "D-LIB" and near[0]["distance_m"] < 50
    detail = client.get(f"/api/routes/{routes[0]['id']}").json()
    assert len(detail["stops"]) >= 2 and detail["path"]
    assert detail["stops"][0]["distance_m"] == 0


def test_meta_flags_demo(client):
    m = client.get("/api/meta").json()
    assert m["demo_mode"] is True and "DEMO" in m["notice"]


def test_journey_planning_direct_and_transfer(client):
    # Railway Station -> Thokar Niaz Baig is direct on DEMO-1
    r = client.post("/api/plan", json={"from_lat": 31.5772, "from_lng": 74.3369, "to_lat": 31.4710, "to_lng": 74.2420})
    opts = r.json()["options"]
    assert opts[0]["transfers"] == 0 and opts[0]["legs"][0]["route_code"] == "DEMO-1"
    assert r.json()["nearest_boarding_stop"]["code"] == "D-RLY"
    # Shahdara -> Wapda Town needs DEMO-2 then DEMO-3 (transfer at Liberty)
    r = client.post("/api/plan", json={"from_lat": 31.6230, "from_lng": 74.2900, "to_lat": 31.4380, "to_lng": 74.2650})
    best = r.json()["options"][0]
    rides = [l for l in best["legs"] if l["type"] == "ride"]
    assert best["transfers"] == 1 and [x["route_code"] for x in rides] == ["DEMO-2", "DEMO-3"]
    assert rides[0]["alight"]["code"] == rides[1]["board"]["code"]


def test_plan_validation(client):
    assert client.post("/api/plan", json={"from_lat": 31.5}).status_code == 422


def test_timetable_filters(client):
    t = client.get("/api/timetable").json()
    assert t["timezone"] == "Asia/Karachi" and len(t["routes"]) == 8
    stop = client.get("/api/stops", params={"q": "Wapda"}).json()[0]
    t2 = client.get("/api/timetable", params={"stop_id": stop["id"]}).json()
    assert {r["code"] for r in t2["routes"]} == {"DEMO-3", "DEMO-3R"}
    assert all(len(r["stops"]) == 1 for r in t2["routes"])


# ----------------------------------------------------------------- driver & GPS
def _driver_trip(client, driver_h):
    r = client.post("/api/driver/trips/start", json={"consent": True}, headers=driver_h)
    assert r.status_code == 201, r.text
    return r.json()


def test_driver_requires_consent_and_role(client, driver_h, passenger_h):
    assert client.post("/api/driver/trips/start", json={"consent": False}, headers=driver_h).status_code == 400
    assert client.post("/api/driver/trips/start", json={"consent": True}, headers=passenger_h).status_code == 403
    assert client.get("/api/driver/me").status_code == 401


def test_trip_gps_flow_and_live_sync(client, driver_h, db):
    me = client.get("/api/driver/me", headers=driver_h).json()
    assert me["bus"]["bus_number"] == "DRV-001" and me["route"]["code"] == "DEMO-1"
    trip = _driver_trip(client, driver_h)
    # resuming returns the same trip instead of creating a duplicate
    again = client.post("/api/driver/trips/start", json={"consent": True}, headers=driver_h).json()
    assert again["id"] == trip["id"] and again["resumed"] is True

    geom = route_geom(db, me["route"]["id"])
    now = utcnow()
    pts = []
    for i in range(6):
        lat, lng, hd = geo.point_at_distance(geom.path, geom.cum, 100 + i * 60)
        pts.append({"lat": lat, "lng": lng, "recorded_at": (now - timedelta(seconds=50 - i * 10)).isoformat(),
                    "accuracy_m": 8, "speed_mps": 6, "heading": hd})
    with client.websocket_connect(f"/ws/live?bus_id={me['bus']['id']}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        r = client.post(f"/api/driver/trips/{trip['id']}/locations", json={"points": pts}, headers=driver_h)
        body = r.json()
        assert r.status_code == 200 and body["accepted"] == 6 and body["rejected"] == []
        msg = ws.receive_json()
        assert msg["type"] == "bus_position" and msg["bus_number"] == "DRV-001"
        assert msg["status"] in ("active", "delayed") and msg["is_demo"] is False
    assert body["state"]["progress_m"] > 300

    # duplicates and invalid points
    dup = client.post(f"/api/driver/trips/{trip['id']}/locations", json={"points": pts[-2:]}, headers=driver_h).json()
    assert dup["accepted"] == 0 and dup["duplicates"] == 2
    bad = client.post(f"/api/driver/trips/{trip['id']}/locations", headers=driver_h, json={"points": [
        {"lat": 24.86, "lng": 67.0, "recorded_at": utcnow().isoformat()},
        {"lat": 31.55, "lng": 74.32, "recorded_at": utcnow().isoformat(), "accuracy_m": 900},
    ]}).json()
    assert {x["reason"] for x in bad["rejected"]} == {"outside_service_area", "low_accuracy"}

    # ETA for the next stop is live
    bus = client.get(f"/api/buses/{me['bus']['id']}").json()
    assert bus["upcoming_stops"] and bus["upcoming_stops"][0]["kind"] == "live"
    stop_id = bus["upcoming_stops"][0]["stop_id"]
    arr = client.get(f"/api/stops/{stop_id}/arrivals").json()
    assert any(a["bus_number"] == "DRV-001" for a in arr["live"])

    end = client.post(f"/api/driver/trips/{trip['id']}/end", json={"reason": "completed"}, headers=driver_h).json()
    assert end["status"] == "completed"
    hist = client.get("/api/driver/trips", headers=driver_h).json()
    assert hist[0]["id"] == trip["id"]
    # a finished trip no longer accepts GPS
    r = client.post(f"/api/driver/trips/{trip['id']}/locations", json={"points": pts[:1]}, headers=driver_h)
    assert r.status_code == 409


def test_driver_cannot_report_other_bus(client, driver_h, db):
    other = db.execute(select(Bus).where(Bus.bus_number == "DEMO-110")).scalars().one()
    t = Trip(bus_id=other.id, route_id=other.route_id, status=TripStatus.active, started_at=utcnow())
    db.add(t)
    db.commit()
    r = client.post(f"/api/driver/trips/{t.id}/locations", headers=driver_h,
                    json={"points": [{"lat": 31.55, "lng": 74.32, "recorded_at": utcnow().isoformat()}]})
    assert r.status_code == 404
    t.status = TripStatus.completed
    db.commit()


def test_offline_trip_gets_interrupted(client, driver_h, db):
    trip = _driver_trip(client, driver_h)
    t = db.get(Trip, trip["id"])
    t.last_update_at = utcnow() - timedelta(hours=2)
    db.commit()
    monitor.check_buses(db)
    db.refresh(t)
    assert t.status == TripStatus.interrupted and t.end_reason == "gps_timeout"


# ----------------------------------------------------------------- simulator & notifications
def test_simulator_moves_demo_buses_only(db):
    before = {b.bus_number: b.last_gps_at for b in db.execute(select(Bus)).scalars()}
    assert simulator.tick(db) > 0
    db.expire_all()
    after = {b.bus_number: b.last_gps_at for b in db.execute(select(Bus)).scalars()}
    assert after["DEMO-101"] is not None and after["DEMO-101"] != before["DEMO-101"]
    assert after["DRV-001"] == before["DRV-001"]  # never simulated


def test_arrival_watch_notifies(client, passenger_h, db):
    simulator.tick(db)
    bus = db.execute(select(Bus).where(Bus.bus_number == "DEMO-101")).scalars().one()
    trip = db.execute(select(Trip).where(Trip.bus_id == bus.id, Trip.status == TripStatus.active)).scalars().one()
    geom = route_geom(db, trip.route_id)
    nxt = geom.next_stop(trip.progress_m)
    r = client.post("/api/me/watches", headers=passenger_h,
                    json={"stop_id": nxt.stop_id, "route_id": trip.route_id, "bus_id": bus.id, "minutes_before": 30})
    assert r.status_code == 201
    assert monitor.check_watches(db) >= 1
    notes = client.get("/api/me/notifications", headers=passenger_h).json()
    assert notes and notes[0]["kind"] in ("bus_approaching", "bus_arriving") and "DEMO" in notes[0]["title"]


def test_favorites_prefs_and_disruption_notification(client, passenger_h, admin_h):
    route = client.get("/api/routes", params={"q": "DEMO-4"}).json()[0]
    stop = client.get("/api/stops", params={"q": "GPO"}).json()[0]
    assert client.put(f"/api/me/favorites/routes/{route['id']}", headers=passenger_h).status_code == 204
    assert client.put(f"/api/me/favorites/routes/{route['id']}", headers=passenger_h).status_code == 204  # idempotent
    assert client.put(f"/api/me/favorites/stops/{stop['id']}", headers=passenger_h).status_code == 204
    fav = client.get("/api/me/favorites", headers=passenger_h).json()
    assert fav["routes"][0]["id"] == route["id"] and fav["stops"][0]["id"] == stop["id"]
    prefs = client.put("/api/me/notification-preferences", headers=passenger_h, json={"delays": False}).json()
    assert prefs["delays"] is False and prefs["disruptions"] is True
    client.post("/api/admin/alerts", headers=admin_h, json={
        "route_id": route["id"], "severity": "disruption", "title": "Road closure at Jail Road",
        "message": "Buses diverted (demo alert)."})
    notes = client.get("/api/me/notifications", headers=passenger_h).json()
    assert any(n["kind"] == "disruption" for n in notes)
    assert client.get("/api/alerts", params={"route_id": route["id"]}).json()
    client.post("/api/me/journeys", headers=passenger_h, json={"route_id": route["id"]})
    assert client.get("/api/me/journeys", headers=passenger_h).json()[0]["route"]["id"] == route["id"]


def test_notification_prefs_block_kind(db):
    from app.services.notifications import notify

    u = db.execute(select(User).where(User.email == "passenger@speedolive.demo")).scalars().one()
    u.notification_prefs = dict(u.notification_prefs, delays=False)
    assert notify(db, u, "delay", "t", "b") is None
    assert notify(db, u, "disruption", "t", "b", dedupe_key="x1") is not None
    assert notify(db, u, "disruption", "t", "b", dedupe_key="x1") is None  # de-duplicated
    db.rollback()


# ----------------------------------------------------------------- admin
def test_admin_permissions(client, passenger_h, driver_h):
    for h in (passenger_h, driver_h, {}):
        assert client.get("/api/admin/overview", headers=h).status_code in (401, 403)


def test_admin_overview_and_crud(client, admin_h):
    ov = client.get("/api/admin/overview", headers=admin_h).json()
    assert ov["total_routes"] == 8 and ov["total_buses"] >= 17
    s1 = client.post("/api/admin/stops", headers=admin_h, json={"code": "T-1", "name": "Test Stop A", "lat": 31.50, "lng": 74.30}).json()
    s2 = client.post("/api/admin/stops", headers=admin_h, json={"code": "T-2", "name": "Test Stop B", "lat": 31.52, "lng": 74.31}).json()
    s3 = client.post("/api/admin/stops", headers=admin_h, json={"code": "T-3", "name": "Test Stop C", "lat": 31.53, "lng": 74.33}).json()
    r = client.post("/api/admin/routes", headers=admin_h, json={
        "code": "T-R1", "name": "Test Route", "stops": [
            {"stop_id": s1["id"], "offset_minutes": 0}, {"stop_id": s2["id"], "offset_minutes": 6},
            {"stop_id": s3["id"], "offset_minutes": 12}]})
    assert r.status_code == 201, r.text
    route = r.json()
    assert route["start_stop"]["id"] == s1["id"] and route["end_stop"]["id"] == s3["id"] and route["length_m"] > 2000
    # reorder stops
    r = client.patch(f"/api/admin/routes/{route['id']}", headers=admin_h, json={"stops": [
        {"stop_id": s3["id"], "offset_minutes": 0}, {"stop_id": s2["id"], "offset_minutes": 5},
        {"stop_id": s1["id"], "offset_minutes": 11}]})
    assert [s["id"] for s in r.json()["stops"]] == [s3["id"], s2["id"], s1["id"]]
    assert client.post("/api/admin/routes", headers=admin_h, json={"code": "T-R1", "name": "dup"}).status_code == 409
    # schedule management
    sc = client.post("/api/admin/schedules", headers=admin_h, json={
        "route_id": route["id"], "first_departure": "07:00", "last_departure": "09:00", "frequency_minutes": 30})
    assert sc.status_code == 201 and sc.json()["days"][0] == "mon"
    bad = client.post("/api/admin/schedules", headers=admin_h, json={
        "route_id": route["id"], "first_departure": "10:00", "last_departure": "09:00"})
    assert bad.status_code == 422
    sid = sc.json()["id"]
    up = client.put(f"/api/admin/schedules/{sid}", headers=admin_h, json={
        "route_id": route["id"], "first_departure": "06:30", "last_departure": "09:00", "frequency_minutes": 15})
    assert up.json()["first_departure"] == "06:30"
    # bus + driver
    bus = client.post("/api/admin/buses", headers=admin_h, json={"bus_number": "T-BUS-1", "route_id": route["id"]}).json()
    drv = client.post("/api/admin/drivers", headers=admin_h, json={
        "full_name": "Test Driver", "phone": "03111111111", "password": "drive1234", "license_number": "LIC-T1",
        "bus_id": bus["id"]})
    assert drv.status_code == 201, drv.text
    assert drv.json()["assigned_bus"]["id"] == bus["id"]
    d_h = login(client, "03111111111", "drive1234")
    assert client.get("/api/driver/me", headers=d_h).json()["route"]["code"] == "T-R1"
    client.patch(f"/api/admin/drivers/{drv.json()['id']}", headers=admin_h, json={"is_active": False})
    assert client.post("/api/auth/login", json={"identifier": "03111111111", "password": "drive1234"}).status_code == 403
    # deactivate bus
    assert client.delete(f"/api/admin/buses/{bus['id']}", headers=admin_h).status_code == 204
    fleet = client.get("/api/admin/fleet", headers=admin_h).json()["buses"]
    assert next(b for b in fleet if b["bus_number"] == "T-BUS-1")["status"] == "out_of_service"
    assert client.delete(f"/api/admin/stops/{s1['id']}", headers=admin_h).status_code == 409  # still used


def test_public_bus_data_hides_driver_details(client):
    live = client.get("/api/buses/live").json()
    text = json.dumps(live)
    assert "+923000000001" not in text and "Demo Driver" not in text and "license" not in text


def test_csv_import(client, admin_h):
    routes_csv = (
        "route_code,route_name,sequence,stop_code,stop_name,lat,lng,offset_minutes,is_major\n"
        "IMP-1,Imported Route,1,IMP-A,Imported A,31.50,74.30,0,1\n"
        "IMP-1,Imported Route,2,IMP-B,Imported B,31.51,74.31,5,0\n"
        "IMP-1,Imported Route,3,IMP-C,Imported C,31.52,74.32,10,1\n"
    )
    sched_csv = "route_code,days,first_departure,last_departure,frequency_minutes\nIMP-1,\"mon,tue\",06:00,22:00,15\n"
    r = client.post("/api/admin/import/routes", headers=admin_h, data={"source_reference": "Test fixture"},
                    files={"routes_file": ("r.csv", io.BytesIO(routes_csv.encode()), "text/csv"),
                           "schedules_file": ("s.csv", io.BytesIO(sched_csv.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["routes_created"] == 1 and r.json()["stops_created"] == 3 and r.json()["schedules"] == 1
    rt = client.get("/api/routes", params={"q": "IMP-1"}).json()[0]
    assert rt["is_demo"] is False and rt["source_reference"] == "Test fixture"
    bad = client.post("/api/admin/import/routes", headers=admin_h, data={"source_reference": "Test fixture"},
                      files={"routes_file": ("r.csv", io.BytesIO(b"route_code,lat\nX,1\n"), "text/csv")})
    assert bad.status_code == 422


def test_reports(client, admin_h):
    rep = client.get("/api/admin/reports", params={"days": 7}, headers=admin_h).json()
    assert {"daily_trips", "bus_activity", "route_usage", "delayed_trips", "service_interruptions"} <= rep.keys()
    assert rep["summary"]["trips"] >= 1
    csv_r = client.get("/api/admin/reports/bus_activity.csv", headers=admin_h)
    assert csv_r.status_code == 200 and "bus_number" in csv_r.text


def test_openapi_docs(client):
    spec = client.get("/openapi.json").json()
    assert "/api/plan" in spec["paths"] and "/api/driver/trips/{trip_id}/locations" in spec["paths"]
