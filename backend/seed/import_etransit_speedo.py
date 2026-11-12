"""Build seed/speedo_network.json from the Punjab Mass Transit Authority e-Transit route planner.

Source page: https://etransit.punjab.gov.pk/public/route-planner?city=110&line=42
Only line 42 ("LFR- Speedo", Lahore) is imported: its routes, stops (forward direction,
in order, with coordinates) and the day's timetable (first / last departure, average headway).

Usage (from the backend folder):
    python seed/import_etransit_speedo.py              # download fresh data (1 request/second)
    python seed/import_etransit_speedo.py --cache DIR  # reuse DIR/<route_id>.json files saved earlier

Then delete backend/data/speedo.db and restart so the app seeds the new network.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

API = "https://etransit.punjab.gov.pk/repo/backend/public/api"
LINE_ID = 42          # LFR- Speedo
DISTRICT_ID = 110     # Lahore
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "speedo_network.json")
UA = "SpeedoLive-importer/1.0"
AREA = (31.20, 31.80, 74.00, 74.60)  # must match AREA_* in config


def _req(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}/{path}", data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def haversine(a, b) -> float:
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def clean_stop_name(name: str) -> str:
    n = re.sub(r"\s*\b(lfr|lrf)\b\s*(up|down|dn)?\s*$", "", name.strip(), flags=re.I)
    n = re.sub(r"\s+(up|down)\s*$", "", n, flags=re.I)
    n = re.sub(r"\s{2,}", " ", n).strip(" -")
    return n or name.strip()


def short_code(headsign: str, used: set[str]) -> str:
    c = re.sub(r"\s+to\s+", " – ", headsign.strip(), flags=re.I)
    c = re.sub(r"\b(\w+) \1\b", r"\1", c, flags=re.I)  # "Station Station" -> "Station"
    for a, b in (("Railway Station", "Railway Stn"), ("Station", "Stn"), ("Terminal", "Term."),
                 ("Headquarter", "HQ"), ("Underpass", "U/pass"), ("Chowk", "Chk")):
        if len(c) <= 32:
            break
        c = c.replace(a, b)
    c = c[:32].rstrip()
    base, i = c, 2
    while c in used:
        c = f"{base[:29]} {i}"; i += 1
    used.add(c)
    return c


def palette(n: int) -> list[str]:
    out = []
    for i in range(n):
        hue = (i * 0.618034) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.42, 0.75)
        out.append("#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255)))
    out[0] = "#D0102B"  # first route in Speedo red
    return out


def hhmm(ts: str) -> str:
    return ts[11:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="folder with <route_id>.json responses saved earlier")
    args = ap.parse_args()

    planner = _req("home-page/districts-with-lines?page=planner")["data"]
    line = next((l for l in planner["lines"].get(f"district-{DISTRICT_ID}", []) if l["id"] == LINE_ID), None)
    if not line:
        sys.exit("Speedo line not found in the e-Transit dataset")
    main_routes = [r for r in planner["routes"] if r["line_id"] == LINE_ID]
    print(f"{line['line_name']}: {len(main_routes)} routes")

    stops: dict[str, dict] = {}
    routes = []
    skipped: list[str] = []
    used_codes: set[str] = set()
    colors = palette(len(main_routes))
    for idx, mr in enumerate(sorted(main_routes, key=lambda r: r["headsign"])):
        if args.cache and os.path.exists(os.path.join(args.cache, f"{mr['id']}.json")):
            with open(os.path.join(args.cache, f"{mr['id']}.json"), encoding="utf-8") as fh:
                data = json.load(fh)["data"]
        else:
            data = _req("home-page/get-line-schedules", {"line_id": LINE_ID, "main_route_id": mr["id"]})["data"]
            time.sleep(1)
        fwd = data.get("forward") or data.get("backward")
        if not fwd or len(fwd.get("stops") or []) < 2:
            print("  skip (no stops):", mr["headsign"]); continue

        headsign = (fwd.get("route_long_name") or mr["headsign"]).strip()
        raw = sorted(fwd["stops"], key=lambda s: int(s["sequence"]))
        ll = [(float(s["latitude"]), float(s["longitude"])) for s in raw]
        bad = set()
        for i in range(1, len(raw) - 1):  # far from both neighbours, which are close to each other = wrong coordinates
            if haversine(ll[i - 1], ll[i]) > 3000 and haversine(ll[i], ll[i + 1]) > 3000 and haversine(ll[i - 1], ll[i + 1]) < 3000:
                bad.add(i)
        seq, seen = [], set()
        for i, s in enumerate(raw):
            lat, lon = ll[i]
            if i in bad:
                print(f"  wrong coordinates in source, skipped: {s['name']} ({lat}, {lon})")
                skipped.append(f"{headsign}: {s['name']}"); continue
            if not (AREA[0] <= lat <= AREA[1] and AREA[2] <= lon <= AREA[3]):
                print("  stop outside Lahore area, skipped:", s["name"])
                skipped.append(f"{headsign}: {s['name']}"); continue
            code = f"ET{s['id']}"
            if code in seen:
                continue
            seen.add(code); seq.append(code)
            stops.setdefault(code, {"code": code, "name": clean_stop_name(s["name"]), "name_ur": None, "lat": lat, "lon": lon})
        if len(seq) < 2:
            continue

        # timetable from the first stop's departures (today's service as published)
        times = sorted({hhmm(t["start_time"]) for t in fwd["stops"][0].get("timings") or []})
        if len(times) >= 2:
            t0, t1 = (datetime.strptime(x, "%H:%M") for x in (times[0], times[-1]))
            headway = max(3, round((t1 - t0).seconds / 60 / (len(times) - 1)))
        else:
            headway = 20
        first, last = (times[0], times[-1]) if times else ("06:00", "22:00")

        # average speed: route length / scheduled run time of the first trip
        pts = [(stops[c]["lat"], stops[c]["lon"]) for c in seq]
        length = sum(haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        speed = 18.0
        first_t = (fwd["stops"][0].get("timings") or [{}])[0].get("start_time")
        last_ts = [t["start_time"] for t in (fwd["stops"][-1].get("timings") or [])]
        if first_t and last_ts:
            later = [t for t in last_ts if t > first_t]
            if later:
                mins = (datetime.fromisoformat(min(later)) - datetime.fromisoformat(first_t)).seconds / 60
                if mins > 5:
                    speed = round(min(30.0, max(10.0, length / 1000 / (mins / 60))), 1)

        name = re.sub(r"\b(\w+) \1\b", r"\1", headsign, flags=re.I).replace(" to ", " ↔ ")
        routes.append({
            "code": short_code(headsign, used_codes), "name": name, "color": colors[idx],
            "avg_speed_kmh": speed, "etransit_route_id": mr["id"], "stops": seq,
            "schedule": {"days": "MON,TUE,WED,THU,FRI,SAT,SUN", "first_departure": first, "last_departure": last, "headway_min": headway},
        })
        print(f"  {routes[-1]['code']:<33} {len(seq):>2} stops  {length/1000:5.1f} km  {first}-{last} every {headway} min  {speed} km/h")

    # simulated buses (positions are simulated; the network and timetables are real)
    buses, n = [], 0
    for i, r in enumerate(routes):
        for j in range(2):
            n += 1
            profile = "SLOW" if (i == 0 and j == 1) else "DROPOUT" if (i == 1 and j == 1) else "NORMAL"
            buses.append({"bus_number": f"SP-{100 + n}", "route": r["code"], "device": f"SIM-{profile}-{100 + n}"})
    buses.append({"bus_number": f"SP-{100 + n + 1}", "route": routes[0]["code"], "device": None, "driver": "driver1"})

    out = {
        "_notice": "Speedo network (routes, stops, timetables) imported from the Punjab Mass Transit Authority "
                   "e-Transit route planner (etransit.punjab.gov.pk, line 42 'LFR- Speedo'). "
                   f"Imported {datetime.now():%Y-%m-%d}. Bus positions are simulated until real GPS is connected.",
        "source": "Punjab Mass Transit Authority · e-Transit",
        "skipped_stops": skipped,
        "stops": sorted(stops.values(), key=lambda s: s["code"]),
        "routes": routes,
        "buses": buses,
        "drivers": [
            {"key": "driver1", "name": "Ali Raza", "email": "driver@speedo.demo", "phone": "03000000001", "employee_code": "SP-DRV-01"},
            {"key": "driver2", "name": "Usman Tariq", "email": "driver2@speedo.demo", "phone": "03000000002", "employee_code": "SP-DRV-02"},
        ],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"wrote {OUT}: {len(routes)} routes, {len(stops)} stops, {len(buses)} buses")


if __name__ == "__main__":
    main()
