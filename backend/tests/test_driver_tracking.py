"""Driver app flow, GPS validation, live status, ETA and the real-time stream.
Tests in this module run in order and share the SP-103 trip."""
import datetime as dt
import json
import threading
import urllib.request

import pytest

from app.db import get_db, iso
from app.services.network import network

STATE = {"clock": 45.0}


def nxt(step: float = 2.0) -> float:
    """Monotonic fake 'seconds ago' clock: fixes are 2 s apart, ending slightly in the future
    (within the allowed clock skew)."""
    STATE["clock"] -= step
    return STATE["clock"]


def ts(seconds_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)).isoformat()


def pt(chainage: float, seconds_ago: float, **kw) -> dict:
    lat, lon, heading = network.get(1).polyline.point_at(chainage)
    return {"lat": lat, "lon": lon, "accuracy_m": 8, "speed_mps": 6, "heading": round(heading, 1),
            "recorded_at": ts(seconds_ago), **kw}


def test_driver_profile_shows_assigned_bus(client, tokens):
    s, me = client.get("/api/driver/me", token=tokens["driver"])
    assert s == 200 and me["bus"]["bus_number"] == "SP-103" and me["route"]["code"] == "Thokar – Railway"
    assert me["trip"] is None and me["driver"]["location_consent_at"] is None


def test_non_drivers_cannot_use_driver_api(client, tokens):
    s, d = client.post("/api/driver/location", pt(100, 0), token=tokens["passenger"])
    assert s == 403 and d["error"]["code"] == "forbidden"
    assert client.post("/api/driver/location", pt(100, 0), token="")[0] == 401


def test_driver_without_bus(client, tokens):
    client.post("/api/driver/consent", {"accepted": True}, token=tokens["driver2"])
    s, d = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tokens["driver2"])
    assert s == 409 and d["error"]["code"] == "no_bus_assigned"


def test_trip_needs_consent_then_starts(client, tokens):
    s, d = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tokens["driver"])
    assert s == 412 and d["error"]["code"] == "consent_required"
    assert client.post("/api/driver/consent", {"accepted": True}, token=tokens["driver"])[0] == 200
    s, trip = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tokens["driver"])
    assert s == 201 and trip["status"] == "active" and trip["source"] == "driver"
    STATE["trip_id"] = trip["id"]
    # starting again (app restart) resumes the same trip
    s, again = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tokens["driver"])
    assert again["id"] == trip["id"]


def test_location_before_any_fix_bus_is_stale_not_hidden(client):
    s, b = client.get("/api/buses/3")
    assert b["status"] == "stale" and b["position"] is None


def test_send_locations_and_live_position(client, tokens):
    # backdate trip start so a short history of fixes is valid
    get_db().execute("UPDATE trips SET started_at = ? WHERE id = ?", (ts(120), STATE["trip_id"]))
    for i, ch in enumerate(range(400, 700, 30)):
        s, r = client.post("/api/driver/location", pt(ch, nxt()), token=tokens["driver"])
        assert s == 200 and r["accepted"] == 1 and r["live_updated"], r
    s, b = client.get("/api/buses/3")
    assert b["status"] in ("active", "delayed") and b["position"]["moving"] is True
    assert b["next_stop"]["name"] == "Emporium Mall (Johar Town)" and b["next_stop"]["eta_s"] > 0
    assert b["gps_age_s"] <= 45 and b["last_gps_at"]


def test_invalid_coordinates_rejected(client, tokens):
    s, d = client.post("/api/driver/location", {"lat": 95, "lon": 74.3, "recorded_at": ts(0)}, token=tokens["driver"])
    assert s == 422
    s, r = client.post("/api/driver/location", {"lat": 24.86, "lon": 67.0, "recorded_at": ts(0)}, token=tokens["driver"])  # Karachi
    assert s == 200 and r["accepted"] == 0 and r["rejected"][0]["reason"] == "outside_service_area"
    s, d = client.post("/api/driver/location", {"lat": 31.5, "lon": 74.3, "recorded_at": "2026-11-04T10:00:00"}, token=tokens["driver"])
    assert s == 422  # timestamp without timezone


def test_timestamp_accuracy_duplicate_and_jump_checks(client, tokens):
    s, r = client.post("/api/driver/location", pt(720, -600), token=tokens["driver"])
    assert r["rejected"][0]["reason"] == "timestamp_in_future"
    s, r = client.post("/api/driver/location", pt(720, nxt(), accuracy_m=500), token=tokens["driver"])
    assert r["rejected"][0]["reason"] == "accuracy_too_low"
    last = get_db().one("SELECT last_gps_at FROM trips WHERE id = ?", (STATE["trip_id"],))["last_gps_at"]
    p = pt(690, 0)
    p["recorded_at"] = last
    s, r = client.post("/api/driver/location", p, token=tokens["driver"])
    assert r["duplicates"] == 1 and r["accepted"] == 0
    s, r = client.post("/api/driver/location", pt(9000, nxt()), token=tokens["driver"])  # 8 km in ~2 s
    assert r["rejected"][0]["reason"] == "implausible_jump"


def test_low_accuracy_fix_is_flagged(client, tokens):
    s, r = client.post("/api/driver/location", pt(730, nxt(), accuracy_m=80), token=tokens["driver"])
    assert r["accepted"] == 1
    row = get_db().one("SELECT low_accuracy FROM gps_locations WHERE trip_id = ? ORDER BY recorded_at DESC LIMIT 1", (STATE["trip_id"],))
    assert row["low_accuracy"]
    assert client.get("/api/buses/3")[1]["position"]["low_accuracy"] is True


def test_offline_queue_batch_out_of_order(client, tokens):
    a, b, c = nxt(), nxt(), nxt()
    first = pt(745, a)
    pts = [pt(760, b), first, pt(790, c), dict(first)]  # unordered + one duplicate
    s, r = client.post("/api/driver/location/batch", {"points": pts}, token=tokens["driver"])
    assert s == 200 and r["accepted"] == 3 and r["duplicates"] == 1
    b = get_db().one("SELECT last_chainage_m FROM buses WHERE id = 3")
    assert abs(b["last_chainage_m"] - 790) < 30  # newest fix wins


def test_eta_decreases_as_bus_approaches(client, tokens):
    s, a1 = client.get("/api/stops/3/arrivals?route_id=1")
    e1 = next(x for x in a1["live"] if x["bus_number"] == "SP-103")
    for i, ch in enumerate(range(820, 1300, 30)):
        client.post("/api/driver/location", pt(ch, nxt()), token=tokens["driver"])
    s, a2 = client.get("/api/stops/3/arrivals?route_id=1")
    e2 = next(x for x in a2["live"] if x["bus_number"] == "SP-103")
    assert e2["distance_m"] < e1["distance_m"] and e2["eta_s"] < e1["eta_s"]
    assert e2["sources"]["observed_kmh"] is not None and e2["confidence"] in ("high", "medium")


def test_stale_and_offline_detection(client):
    db = get_db()
    real = db.one("SELECT last_gps_at FROM buses WHERE id = 3")["last_gps_at"]
    for age, expected in ((60, "stale"), (400, "offline")):
        old = ts(age)
        db.execute("UPDATE buses SET last_gps_at = ? WHERE id = 3", (old,))
        db.execute("UPDATE trips SET last_gps_at = ? WHERE id = ?", (old, STATE["trip_id"]))
        s, b = client.get("/api/buses/3")
        assert b["status"] == expected and b["next_stop"] is None
        a = client.get("/api/stops/9/arrivals?route_id=1")[1]
        assert all(x["bus_number"] != "SP-103" for x in a["live"])  # no fake live ETA from stale data
    db.execute("UPDATE buses SET last_gps_at = ? WHERE id = 3", (real,))
    db.execute("UPDATE trips SET last_gps_at = ? WHERE id = ?", (real, STATE["trip_id"]))


def test_stopped_bus_with_fresh_gps_is_not_stale(client, tokens):
    s, r = client.post("/api/driver/location", pt(1300, nxt(), speed_mps=0), token=tokens["driver"])
    assert r["accepted"] == 1
    b = client.get("/api/buses/3")[1]
    assert b["status"] in ("active", "delayed") and b["position"]["moving"] is False


def test_sse_stream_pushes_updates(server, client, tokens):
    events = []
    got_update = threading.Event()

    def listen():
        req = urllib.request.Request(server + "/api/live/stream?bus_id=3", headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            name = None
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    events.append((name, json.loads(line[5:])))
                    if name == "bus":
                        got_update.set()
                        return

    th = threading.Thread(target=listen, daemon=True)
    th.start()
    for _ in range(50):
        if events:
            break
        threading.Event().wait(0.1)
    assert events and events[0][0] == "snapshot" and [b["id"] for b in events[0][1]["buses"]] == [3]
    client.post("/api/driver/location", pt(1340, nxt()), token=tokens["driver"])
    assert got_update.wait(10)
    bus = events[-1][1]["bus"]
    assert bus["id"] == 3 and bus["position"] and "driver" not in bus


def test_admin_stream_requires_valid_ticket(server, client, tokens):
    s, d = client.get("/api/live/stream?ticket=bogus")
    assert s == 401
    s, t = client.post("/api/admin/stream-ticket", token=tokens["admin"])
    req = urllib.request.Request(server + f"/api/live/stream?ticket={t['ticket']}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                snap = json.loads(line[5:])
                assert any(b.get("driver") for b in snap["buses"])  # admin view includes driver
                break


def test_driver_cannot_post_after_trip_end_and_history(client, tokens):
    s, t = client.post("/api/driver/trips/end", {"reason": "completed"}, token=tokens["driver"])
    assert s == 200 and t["status"] == "completed"
    s, d = client.post("/api/driver/location", pt(1400, nxt()), token=tokens["driver"])
    assert s == 409 and d["error"]["code"] == "no_active_trip"
    s, hist = client.get("/api/driver/trips", token=tokens["driver"])
    assert hist[0]["id"] == STATE["trip_id"] and hist[0]["gps_points"] >= 20


def test_driver_logout_interrupts_active_trip(client):
    tok = client.login("driver@speedo.demo")
    s, trip = client.post("/api/driver/trips/start", {"direction": "inbound"}, token=tok)
    assert s == 201
    client.post("/api/auth/logout", token=tok)
    row = get_db().one("SELECT status, end_reason FROM trips WHERE id = ?", (trip["id"],))
    assert row["status"] == "interrupted" and row["end_reason"] == "driver_logout"


def test_withdrawing_consent_stops_sharing(client):
    tok = client.login("driver@speedo.demo")
    s, trip = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tok)
    client.post("/api/driver/consent", {"accepted": False}, token=tok)
    assert get_db().one("SELECT status FROM trips WHERE id = ?", (trip["id"],))["status"] == "interrupted"
    s, d = client.post("/api/driver/trips/start", {"direction": "outbound"}, token=tok)
    assert s == 412
    client.post("/api/driver/consent", {"accepted": True}, token=tok)
