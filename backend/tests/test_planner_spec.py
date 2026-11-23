"""Journey planner checks from the development spec (sections 4-6, 11, 13).

All fixtures here are SYNTHETIC: the seeded DEMO-1..DEMO-8 one-way routes from app/seed.py, not real Speedo data.
"""
RLY = {"from_lat": 31.5772, "from_lng": 74.3369}  # Railway Station (Demo)
THK = {"to_lat": 31.4710, "to_lng": 74.2420}  # Thokar Niaz Baig (Demo)
SHAHDARA_TO_WAPDA = {"from_lat": 31.6230, "from_lng": 74.2900, "to_lat": 31.4380, "to_lng": 74.2650}


def _rides(option):
    return [l for l in option["legs"] if l["type"] == "ride"]


def test_plan_is_labelled_honestly(client):
    r = client.post("/api/plan", json=RLY | THK).json()
    assert r["status"] == "ok" and r["prefer"] == "fastest"
    assert r["search_limits"] == {"max_walk_m": 1500, "max_transfers": 2, "max_transfer_walk_m": 300}
    assert r["dataset"]["route_count"] >= 1 and "sources" in r["dataset"]
    ids = [o["itinerary_id"] for o in r["options"]]
    assert len(set(ids)) == len(ids) and all(len(i) == 12 for i in ids)
    assert 1 <= len(r["options"]) <= 3  # one recommended + at most two alternatives
    assert [o["recommended"] for o in r["options"]] == [True] + [False] * (len(r["options"]) - 1)
    for o in r["options"]:
        assert o["timing_basis"] == "timetable_estimate"
        assert o["fare_pkr"] is None  # the synthetic routes have no fare: unknown, not 0
        for leg in o["legs"]:
            if leg["type"] == "walk":
                assert leg["estimate_basis"] == "straight_line"


def test_every_ride_leg_is_valid_and_in_order(client):
    for body in (RLY | THK, SHAHDARA_TO_WAPDA):
        for o in client.post("/api/plan", json=body).json()["options"]:
            rides = _rides(o)
            assert o["transfers"] == len(rides) - 1
            for leg in rides:
                route = client.get(f"/api/routes/{leg['route_id']}").json()
                seq = {s["id"]: s["sequence"] for s in route["stops"]}
                ids = [s["id"] for s in leg["stops"]]
                assert ids[0] == leg["board"]["id"] and ids[-1] == leg["alight"]["id"]
                assert [seq[i] for i in ids] == sorted(seq[i] for i in ids)  # boarding before alighting
            legs = o["legs"]
            for i, leg in enumerate(legs):  # every transfer connects: same stop, or a short walk between stops
                if leg["type"] != "ride" or leg is rides[-1]:
                    continue
                nxt = legs[i + 1]
                if nxt["type"] == "ride":
                    assert leg["alight"]["id"] == nxt["board"]["id"]
                else:
                    assert nxt.get("transfer") and nxt["distance_m"] <= 300
                    assert nxt["from"]["id"] == leg["alight"]["id"] and nxt["to"]["id"] == legs[i + 2]["board"]["id"]


def test_opposite_direction_is_rejected(client):
    """DEMO-1 runs Railway -> Thokar only, so it must never be offered Thokar -> Railway."""
    body = {"from_lat": 31.4710, "from_lng": 74.2420, "to_lat": 31.5772, "to_lng": 74.3369}
    for o in client.post("/api/plan", json=body).json()["options"]:
        assert all(l["route_code"] != "DEMO-1" for l in _rides(o))


def test_preferences_change_the_ranking(client):
    few = client.post("/api/plan", json=SHAHDARA_TO_WAPDA | {"prefer": "fewer_transfers"}).json()["options"]
    assert [o["transfers"] for o in few] == sorted(o["transfers"] for o in few)
    walk = client.post("/api/plan", json=SHAHDARA_TO_WAPDA | {"prefer": "less_walking"}).json()["options"]
    assert [o["walk_m"] for o in walk] == sorted(o["walk_m"] for o in walk)
    assert client.post("/api/plan", json=SHAHDARA_TO_WAPDA | {"prefer": "cheapest"}).status_code == 422


def test_no_route_reports_search_limits_not_absolute(client):
    # both ends far outside the network (still inside the coordinate range): nothing within the limits
    r = client.post("/api/plan", json={"from_lat": 31.74, "from_lng": 74.64, "to_lat": 31.21, "to_lng": 74.01}).json()
    assert r["status"] == "no_route" and r["options"] == []
    codes = {w["code"] for w in r["warnings"]}
    assert codes & {"origin_no_stop", "origin_far_from_stops"}
    assert r["search_limits"]["max_walk_m"] == 1500


def test_walking_transfer_neighbours(db):
    """Stops within the transfer radius are linked both ways (including the stop itself); far ones are not."""
    from app.config import get_settings
    from app.models import BusStop
    from app.services.planner import _neighbours
    from app.services.geo import haversine_m

    near = _neighbours(db, get_settings().max_transfer_walk_m)
    stops = {s.id: s for s in db.all(BusStop)}
    for sid, lst in near.items():
        assert (sid, 0.0) in lst  # (another stop at the very same spot may also be at 0 m)
        for oid, d in lst:
            assert d <= 300 and any(x == sid for x, _ in near[oid])
            assert abs(d - haversine_m(stops[sid].lat, stops[sid].lng, stops[oid].lat, stops[oid].lng)) < 1
    # brute force: nothing within 300 m is missed
    for a in stops.values():
        found = {x for x, _ in near[a.id]}
        for b in stops.values():
            if haversine_m(a.lat, a.lng, b.lat, b.lng) <= 300:
                assert b.id in found


def test_outside_service_area_is_its_own_state(client):
    """Islamabad -> Lahore: not 'no route' and no stretched search to a stop far away, but outside_coverage."""
    r = client.post("/api/plan", json={"from_lat": 33.6844, "from_lng": 73.0479, "to_lat": 31.5772, "to_lng": 74.3369}).json()
    assert r["status"] == "outside_coverage" and r["options"] == []
    assert [w["code"] for w in r["warnings"]] == ["origin_outside_area"]


def test_spec_field_names_carry_the_same_estimates(client):
    for o in client.post("/api/plan", json=RLY | THK).json()["options"]:
        assert o["duration_seconds"] == o["total_minutes"] * 60
        assert o["total_walk_distance_m"] == o["walk_m"]


def test_logs_do_not_keep_search_text():
    import logging
    from app.main import _RedactQuery

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", "/api/places?q=Main Model Town mein hoon&lat=31.5", "1.1", 200), None)
    _RedactQuery().filter(rec)
    line = rec.getMessage()
    assert "Model Town" not in line and "31.5" not in line and "/api/places?…" in line
