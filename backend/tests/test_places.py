"""Destination search: Speedo stops first, then any place in Lahore (OpenStreetMap), and planning from 'my location'."""
from app.services import places


def test_places_stops_then_osm_places(client, monkeypatch):
    calls = []

    def fake_fetch(q):
        calls.append(q)
        return [
            {"label": "Emporium Mall, Johar Town", "detail": "Emporium Mall, Johar Town, Lahore", "lat": 31.4668, "lng": 74.2658, "kind": "place"},
            {"label": "Somewhere in Karachi", "detail": "", "lat": 24.86, "lng": 67.0, "kind": "place"},  # outside Lahore
        ]

    monkeypatch.setattr(places, "fetch", fake_fetch)
    places._cache.clear()
    rows = client.get("/api/places", params={"q": "liberty"}).json()
    assert rows[0]["kind"] == "stop" and rows[0]["label"].startswith("Liberty") and rows[0]["stop_id"]
    assert [r["label"] for r in rows if r["kind"] == "place"] == ["Emporium Mall, Johar Town"]
    client.get("/api/places", params={"q": "Liberty "})  # same search, other spelling: served from cache
    assert len(calls) == 1
    assert client.get("/api/places", params={"q": "x"}).status_code == 422


def test_places_survives_osm_failure(client, monkeypatch):
    monkeypatch.setattr(places, "fetch", lambda q: [])
    places._cache.clear()
    rows = client.get("/api/places", params={"q": "Kalma"}).json()
    assert rows and all(r["kind"] == "stop" for r in rows)


def test_plan_from_my_location_to_a_place(client):
    # standing near Railway Station, going to a place (not a stop) near Thokar Niaz Baig
    r = client.post("/api/plan", json={"from_lat": 31.5780, "from_lng": 74.3375, "from_label": "My location",
                                       "to_lat": 31.4715, "to_lng": 74.2425, "to_label": "Thokar market"}).json()
    assert r["nearest_boarding_stop"]["code"] == "D-RLY" and r["nearest_boarding_stop"]["walk_m"] < 300
    first = r["options"][0]["legs"]
    assert first[0]["type"] == "walk" and first[0]["from"]["name"] == "My location"
    assert any(l["type"] == "ride" for l in first) and first[-1]["to"]["name"] == "Thokar market"


def test_two_way_route_can_be_ridden_backwards(client, admin_h, db):
    """A route marked bidirectional (A <-> B) is planned in both directions; a one-way route only forwards."""
    from app.models import Route

    r = db.first(Route, code="DEMO-1")
    stops = sorted(r.stops, key=lambda x: x.sequence)
    a, b = stops[-1].stop, stops[0].stop  # from the end of the line back to its start
    body = {"from_stop_id": a.id, "to_stop_id": b.id}
    assert all(l.get("route_code") != "DEMO-1" for o in client.post("/api/plan", json=body).json()["options"]
               for l in o["legs"] if l["type"] == "ride")
    assert client.patch(f"/api/admin/routes/{r.id}", headers=admin_h, json={"bidirectional": True}).json()["bidirectional"]
    try:
        opts = client.post("/api/plan", json=body).json()["options"]
        ride = next(l for o in opts for l in o["legs"] if l["type"] == "ride" and l["route_code"] == "DEMO-1")
        assert ride["direction"] == "return" and ride["towards"] == b.name
        assert ride["board"]["id"] == a.id and ride["alight"]["id"] == b.id and ride["distance_m"] > 0 and ride["minutes"] > 0
    finally:
        client.patch(f"/api/admin/routes/{r.id}", headers=admin_h, json={"bidirectional": False})


def test_three_bus_journey_when_nothing_simpler(client, admin_h):
    """A -> B on route X, B -> C on route Y, C -> D on route Z: found as a two-transfer journey."""
    pts = [(31.30, 74.05), (31.31, 74.06), (31.32, 74.07), (31.33, 74.08), (31.34, 74.09), (31.35, 74.10)]
    ids = []
    for i, (la, ln) in enumerate(pts):
        ids.append(client.post("/api/admin/stops", headers=admin_h,
                               json={"code": f"X3-{i}", "name": f"Chain stop {i}", "lat": la, "lng": ln}).json()["id"])
    for code, seg in (("X3-A", ids[0:3]), ("X3-B", ids[2:5]), ("X3-C", ids[4:6])):
        r = client.post("/api/admin/routes", headers=admin_h, json={"code": code, "name": code, "stops": [
            {"stop_id": s, "offset_minutes": k * 5} for k, s in enumerate(seg)]})
        assert r.status_code == 201, r.text
    opts = client.post("/api/plan", json={"from_stop_id": ids[0], "to_stop_id": ids[5]}).json()["options"]
    assert opts and opts[0]["transfers"] == 2
    assert [l["route_code"] for l in opts[0]["legs"] if l["type"] == "ride"] == ["X3-A", "X3-B", "X3-C"]
