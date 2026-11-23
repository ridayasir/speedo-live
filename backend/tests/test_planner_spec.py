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
    assert r["search_limits"] == {"max_walk_m": 1500, "max_transfers": 2}
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
            for a, b in zip(rides, rides[1:]):  # every transfer connects at the same stop
                assert a["alight"]["id"] == b["board"]["id"]


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
