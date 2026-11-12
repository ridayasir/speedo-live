def test_health_and_config(client):
    assert client.get("/health")[1]["status"] == "ok"
    s, cfg = client.get("/api/config")
    assert s == 200 and cfg["mode"] == "demo" and cfg["demo"] is True


def test_demo_data_is_labelled(client):
    s, routes = client.get("/api/routes")
    demo = [r for r in routes if r["is_demo"]]
    assert s == 200 and len(demo) == 3
    assert all(r["is_demo"] and not r["verified"] and r["source"] == "Speedo Live" for r in demo)
    s, buses = client.get("/api/buses")
    assert buses and all(b["is_demo"] for b in buses)


def test_route_detail_has_ordered_stops_and_geometry(client):
    s, r = client.get("/api/routes/1")
    assert s == 200 and r["stops"][0]["name"] == "Thokar Niaz Baig" and r["stops"][-1]["name"] == "Lahore Railway Station"
    ch = [x["chainage_m"] for x in r["stops"]]
    assert ch == sorted(ch) and ch[0] == 0 and len(r["shape"]) >= 2
    assert client.get("/api/routes/999")[0] == 404


def test_stop_search_text_and_nearby(client):
    s, rows = client.get("/api/stops?q=chowk")
    assert s == 200 and {r["name"] for r in rows} >= {"Kalma Chowk", "Shadman Chowk"}
    s, rows = client.get("/api/stops?lat=31.5103&lon=74.3445&radius_m=1500")
    assert rows[0]["name"] == "Liberty Market" and rows[0]["distance_m"] < 50
    assert all(rows[i]["distance_m"] <= rows[i + 1]["distance_m"] for i in range(len(rows) - 1))
    assert client.get("/api/stops?lat=200&lon=74")[0] == 422


def test_plan_direct_journey(client):
    s, d = client.post("/api/journeys/plan", {"origin": {"lat": 31.4815, "lon": 74.3035, "label": "PU"},
                                              "destination": {"lat": 31.5605, "lon": 74.3175, "label": "Regal"}})
    assert s == 200 and d["options"]
    best = d["options"][0]
    assert best["type"] == "direct" and best["route_codes"] == ["Thokar – Railway"]
    ride = best["legs"][1]
    assert ride["board"]["name"] == "Punjab University New Campus" and ride["alight"]["name"] == "Regal Chowk (Mall Road)"
    assert ride["direction"] == "outbound" and [x["name"] for x in ride["stops"]][1] == "Muslim Town Mor"
    assert ride["ride_min"] > 0 and best["total_min"] >= ride["ride_min"]


def test_plan_reverse_direction_and_transfer(client):
    s, d = client.post("/api/journeys/plan", {"origin": {"stop_id": 9}, "destination": {"stop_id": 3}})
    assert d["options"][0]["legs"][1]["direction"] == "inbound"
    # Thokar Niaz Baig -> Airport needs Thokar – Railway then Airport – Minar (shared stop Shadman Chowk)
    s, d = client.post("/api/journeys/plan", {"origin": {"stop_id": 1}, "destination": {"stop_id": 10}})
    assert s == 200 and d["options"][0]["type"] == "transfer"
    assert any(l["kind"] == "transfer" for l in d["options"][0]["legs"])


def test_plan_errors(client):
    s, d = client.post("/api/journeys/plan", {"origin": {"lat": 31.40, "lon": 74.10}, "destination": {"stop_id": 3}})
    assert s == 200 and not d["options"] and "walking distance" in d["message"]
    s, d = client.post("/api/journeys/plan", {"origin": {"stop_id": 3}, "destination": {"stop_id": 3}})
    assert s == 422 and d["error"]["code"] == "too_close"
    s, d = client.post("/api/journeys/plan", {"origin": {"label": "x"}, "destination": {"stop_id": 3}})
    assert s == 422


def test_timetable(client):
    s, t = client.get("/api/timetable?route_id=1&stop_id=5&date=2026-11-04")
    assert s == 200 and t["operates_today"] and t["first_departure"] == "06:30" and t["last_departure"] == "22:00"
    assert t["trips_today"] == 94 and len(t["stop_times"]["outbound"]) == 94
    out = t["directions"]["outbound"]["stops"]
    assert out[0]["first"] == "06:30" and out[-1]["offset_min"] > 30
    # Packages – Regal does not run on Sundays (2026-11-08)
    s, t = client.get("/api/timetable?route_id=3&date=2026-11-08")
    assert t["operates_today"] is False and t["trips_today"] == 0


def test_arrivals_include_live_and_scheduled_labels(client):
    s, a = client.get("/api/stops/6/arrivals")
    assert s == 200
    for x in a["live"]:
        assert x["method"] == "live" and x["eta_s"] >= 0 and x["bus_number"] and x["last_gps_at"]
    assert all(x["method"] == "scheduled" for x in a["scheduled"])


def test_bus_detail_upcoming_stops(client):
    s, buses = client.get("/api/buses")
    live = [b for b in buses if b["status"] in ("active", "delayed")]
    s, b = client.get(f"/api/buses/{live[0]['id']}")
    assert s == 200 and "driver" not in b  # no private driver data on public endpoints
    etas = [u["eta_s"] for u in b["upcoming_stops"]]
    assert etas == sorted(etas)


def test_openapi_document(client):
    s, doc = client.get("/openapi.json")
    assert s == 200 and doc["openapi"].startswith("3.")
    assert "/api/driver/location" in doc["paths"] and "/api/journeys/plan" in doc["paths"]
    assert doc["paths"]["/api/admin/buses"]["get"]["security"] == [{"bearerAuth": []}]


def test_unknown_api_path_is_json_404(client):
    s, d = client.get("/api/nope")
    assert s == 404 and d["error"]["code"] == "not_found"
