"""Unit tests: geometry, ETA blending, notifications/watch logic, provider adapter, simulator, passenger account."""
import datetime as dt

import pytest

from app.db import get_db, iso
from app.geo import Polyline, haversine
from app.services import notify
from app.services.network import network


def test_haversine_known_distance():
    # Minar-e-Pakistan to Lahore Railway Station ≈ 3.1 km
    assert 2800 < haversine(31.5925, 74.3095, 31.5772, 74.3366) < 3300


def test_polyline_projection_and_point_at():
    line = Polyline([(31.50, 74.30), (31.50, 74.32), (31.52, 74.32)])
    p = line.project(31.5005, 74.31)
    assert abs(p.chainage - line.cum[1] / 2) < 5 and p.offset < 60
    lat, lon, heading = line.point_at(line.cum[1] + 100)
    assert abs(lon - 74.32) < 1e-6 and 0 <= heading < 5   # heading north on 2nd segment
    # near_chainage keeps the match on the expected part of a route that doubles back
    loop = Polyline([(31.50, 74.30), (31.50, 74.31), (31.5002, 74.30)])
    far = loop.project(31.5001, 74.305, near_chainage=loop.length - 300)
    assert far.chainage > loop.cum[1]


def test_route_lengths_are_plausible(server):
    for r in network.routes().values():
        if r.is_demo:
            assert 5_000 < r.length < 30_000


def test_eta_falls_back_to_route_speed_without_history(server):
    from app.services.eta import blended_speed
    route = network.get(2)
    trip = {"id": -1, "route_id": 2, "direction": "outbound"}
    v, src = blended_speed(trip, route, dt.datetime.now(dt.timezone.utc))
    assert src["observed_kmh"] is None and abs(v - route.avg_speed_mps) < 0.01


def test_notification_dedupe_and_preferences(server):
    db = get_db()
    uid = db.one("SELECT id FROM users WHERE email = 'passenger@speedo.demo'")["id"]
    assert notify.notify(uid, "info", "Hello", "x", dedupe_key="unit-1")
    assert notify.notify(uid, "info", "Hello", "x", dedupe_key="unit-1") is None
    db.execute("UPDATE notification_prefs SET delays = ? WHERE user_id = ?", (False, uid))
    assert notify.notify(uid, "delay", "Late", "x", dedupe_key="unit-2") is None
    db.execute("UPDATE notification_prefs SET delays = ? WHERE user_id = ?", (True, uid))


def test_watch_sends_approaching_notification(server, client, tokens):
    from app.services.eta import arrivals_at_stop
    P = tokens["passenger"]
    # pick a live simulated bus and the next stop it will reach
    target = None
    for b in client.get("/api/buses")[1]:
        if b["is_demo"] and b["next_stop"] and b["status"] in ("active", "delayed") and b["next_stop"]["eta_s"] is not None:
            target = b
            break
    assert target, "expected a simulated bus with a next stop"
    stop_id = target["next_stop"]["id"]
    eta_min = target["next_stop"]["eta_s"] / 60
    s, w = client.post("/api/me/watches", {"route_id": target["route_id"], "stop_id": stop_id, "bus_id": target["id"],
                                           "lead_min": min(30, int(eta_min) + 3)}, token=P)
    assert s == 201
    assert notify.watch_sweep() >= 1
    inbox = client.get("/api/me/notifications", token=P)[1]["items"]
    assert any(target["bus_number"] in n["title"] for n in inbox)
    assert notify.watch_sweep() == 0  # not repeated
    assert client.post("/api/me/watches", {"route_id": 1, "stop_id": 10}, token=P)[0] == 422  # stop not on route


def test_prefs_favorites_history(client, tokens):
    P = tokens["passenger"]
    s, p = client.put("/api/me/notification-preferences", {"approaching": True, "approaching_lead_min": 7, "delays": False,
                                                            "disruptions": True, "schedule_changes": True}, token=P)
    assert s == 200 and p["approaching_lead_min"] == 7 and p["delays"] is False
    assert client.put("/api/me/notification-preferences", {"approaching_lead_min": 99}, token=P)[0] == 422
    client.post("/api/me/favorites/stops", {"id": 6}, token=P)
    favs = client.get("/api/me/favorites", token=P)[1]
    assert any(s["id"] == 6 for s in favs["stops"])
    client.delete("/api/me/favorites/stops/6", token=P)
    assert not any(s["id"] == 6 for s in client.get("/api/me/favorites", token=P)[1]["stops"])
    assert client.post("/api/me/favorites/routes", {"id": 999}, token=P)[0] == 404
    client.post("/api/journeys/plan", {"origin": {"stop_id": 3}, "destination": {"stop_id": 7}}, token=P)
    hist = client.get("/api/me/history", token=P)[1]
    assert hist and hist[0]["route_codes"] == "Thokar – Railway"
    s, d = client.post("/api/me/devices", {"token": "fcm-test-token-123456", "platform": "android"}, token=P)
    assert s == 201 and d["push_enabled_on_server"] is False


def test_provider_adapter_matches_devices(server):
    from app.services.provider import poll_once
    db = get_db()
    db.execute("UPDATE buses SET gps_device_id = ? WHERE bus_number = 'SP-203'", ("TRACKER-203",))
    db.execute("UPDATE buses SET status = 'active' WHERE bus_number = 'SP-203'")
    route = network.get(2)
    lat, lon, _ = route.polyline.point_at(500)
    now = dt.datetime.now(dt.timezone.utc)
    stats = poll_once([{"device_id": "TRACKER-203", "lat": lat, "lon": lon, "speed_mps": 5, "accuracy_m": 9, "recorded_at": iso(now)},
                       {"device_id": "UNKNOWN-9", "lat": lat, "lon": lon, "recorded_at": iso(now)}])
    assert stats == {"received": 2, "matched": 1, "accepted": 1, "unknown_devices": 1}
    trip = db.one("SELECT * FROM trips WHERE bus_id = (SELECT id FROM buses WHERE bus_number = 'SP-203') AND status = 'active'")
    assert trip["source"] == "provider" and trip["direction"] == "outbound"


def test_simulator_moves_buses(server):
    from app.services.simulator import simulator
    db = get_db()
    sb = next(b for b in simulator.buses.values() if b.profile == "NORMAL")
    before = db.one("SELECT last_chainage_m, last_gps_at FROM buses WHERE id = ?", (sb.bus_id,))
    import time
    time.sleep(1.1)
    simulator.step(5)
    after = db.one("SELECT last_chainage_m, last_gps_at FROM buses WHERE id = ?", (sb.bus_id,))
    assert after["last_gps_at"] > before["last_gps_at"]
    trip = db.one("SELECT source FROM trips WHERE bus_id = ? AND status = 'active'", (sb.bus_id,))
    assert trip is None or trip["source"] == "simulator"


def test_retention_purge(server):
    from app.services.tracking import purge_old_locations
    db = get_db()
    row = db.one("SELECT id FROM gps_locations LIMIT 1")
    db.execute("UPDATE gps_locations SET recorded_at = ? WHERE id = ?", (iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=400)), row["id"]))
    assert purge_old_locations() >= 1
    assert db.one("SELECT id FROM gps_locations WHERE id = ?", (row["id"],)) is None
