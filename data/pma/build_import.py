"""Turn the PMA stop lists + OpenStreetMap geocodes into Speedo Live import files.

Writes:
  pma_routes_import.csv   Admin > Routes > Import CSV (one row per stop, in order)
  review.md               what is official, what is estimated, and which stops need checking

Rules (all estimates are labelled in review.md):
  * stop names and order: verbatim from PMA (official)
  * coordinates: the OpenStreetMap match (of up to 5 per name) that keeps the route shortest; off-line matches dropped
  * stops with no usable match: placed between their neighbours on the route (interpolated)
  * offset_minutes: estimated from distance (road factor 1.3, 18 km/h, 0.5 min per stop); PMA publishes no timings
  * return direction: the same stops reversed (PMA lists one direction; feeder buses run both ways)
"""
import csv
import json
import math
import re
from pathlib import Path

from geocode_stops import clean

HERE = Path(__file__).parent
SRC = json.loads((HERE / "pma_routes_2026-11-19.json").read_text(encoding="utf-8"))
CACHE = json.loads((HERE / "geocode_candidates.json").read_text(encoding="utf-8"))
COLORS = ["#1d4ed8", "#ea580c", "#0f766e", "#7c3aed", "#be123c", "#0369a1", "#15803d", "#a16207",
          "#9333ea", "#c2410c", "#0e7490", "#4d7c0f", "#b91c1c", "#1e40af", "#86198f"]
SPEED_KMH, ROAD_FACTOR, DWELL_MIN = 18.0, 1.3, 0.5
SAME_STOP_M = 400  # same name within this distance on two routes = one shared stop


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


SKIP_PENALTY_M = 1500  # leaving a stop unplaced costs as much as a 1.5 km detour


EXACT_BONUS_M = 1200  # an exact name match is worth keeping even if it bends the line a little


def _candidates(name):
    """[(point, bonus)]: exact-name matches get a bonus so they win over skipping the stop."""
    out = []
    for c in CACHE.get(clean(name)) or []:
        p = (c["lat"], c["lng"])
        if all(hav(p, q) > 150 for q, _ in out):
            out.append((p, EXACT_BONUS_M if c.get("score", 0) >= 1.0 else 0))
    return out


def place(names):
    """Pick one OpenStreetMap candidate (or none) per stop so the route is as short and straight as possible.

    Dynamic programming over the stop sequence: a chosen point costs the distance from the previous chosen
    point; leaving a stop out costs SKIP_PENALTY_M. A wrong match far off the line costs more than skipping
    it, so it is dropped. Unplaced stops are then spread between their placed neighbours.
    Returns (points, kind) with kind in found / interpolated.
    """
    cands = [_candidates(n) for n in names]
    n = len(names)
    best = {}  # (i, c) -> (cost, prev)
    for i in range(n):
        for c, (p, bonus) in enumerate(cands[i]):
            options = [(SKIP_PENALTY_M * i, None)]
            for (j, cj), (cost, _) in list(best.items()):
                if j < i:
                    options.append((cost + hav(cands[j][cj][0], p) + SKIP_PENALTY_M * (i - j - 1), (j, cj)))
            cost, prev = min(options, key=lambda o: o[0])
            best[(i, c)] = (cost - bonus, prev)
    end = min(((cost + SKIP_PENALTY_M * (n - 1 - i), (i, c)) for (i, c), (cost, _) in best.items()),
              default=(SKIP_PENALTY_M * n, None), key=lambda o: o[0])
    pts, kind = [None] * n, ["interpolated"] * n
    node = end[1]
    while node:
        i, c = node
        pts[i], kind[i] = cands[i][c][0], "found"
        node = best[node][1]
    idx = [i for i, p in enumerate(pts) if p]
    if len(idx) < 2:
        return None, kind
    for i in range(n):
        if pts[i]:
            continue
        before = max((j for j in idx if j < i), default=None)
        after = min((j for j in idx if j > i), default=None)
        if before is not None and after is not None:
            t = (i - before) / (after - before)
            a, b = pts[before], pts[after]
            pts[i] = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        else:  # beyond the first/last placed stop: continue the line's average step
            j, k = (idx[0], idx[1]) if before is None else (idx[-1], idx[-2])
            d = ((pts[j][0] - pts[k][0]) / abs(j - k), (pts[j][1] - pts[k][1]) / abs(j - k))
            steps = abs(i - j)
            pts[i] = (pts[j][0] + d[0] * steps, pts[j][1] + d[1] * steps)
    return pts, kind


def slug(n):
    return re.sub(r"[^A-Z0-9]+", "-", n.upper()).strip("-")[:24]


def main():
    registry = []  # dicts: code, key, name, lat, lng, routes
    rows, report, stats = [], [], {"found": 0, "interpolated": 0}
    for ci, (code, r) in enumerate(SRC["routes"].items()):
        pts, kind = place(r["stops"])
        if pts is None:
            report.append(f"| {code} | {r['from']} - {r['to']} | {len(r['stops'])} | **skipped: fewer than 2 stops located** | |")
            continue
        seq_codes = []
        for n, p in zip(r["stops"], pts):
            key = re.sub(r"\s+", " ", n.strip().lower())  # exact PMA name: "Railway Station-2" is its own stop
            hit = next((s for s in registry if s["key"] == key and hav((s["lat"], s["lng"]), p) <= SAME_STOP_M), None)
            if not hit:
                base = "PMA-" + slug(n)
                c, k = base, 2
                while any(s["code"] == c for s in registry):
                    c, k = f"{base}-{k}", k + 1
                hit = {"code": c, "key": key, "name": n, "lat": round(p[0], 6), "lng": round(p[1], 6), "routes": set()}
                registry.append(hit)
            hit["routes"].add(code)
            seq_codes.append(hit)
        for k in kind:
            stats[k] += 1
        route_rows = []
        for direction in ("", "R"):
            stops = seq_codes if not direction else list(reversed(seq_codes))
            name = f"{code}: {r['from']} - {r['to']}" if not direction else f"{code} (return): {r['to']} - {r['from']}"
            off, total = 0.0, []
            for i, s in enumerate(stops):
                if i:
                    off += hav((stops[i - 1]["lat"], stops[i - 1]["lng"]), (s["lat"], s["lng"])) * ROAD_FACTOR / (SPEED_KMH * 1000 / 60) + DWELL_MIN
                total.append(round(off, 1))
            for i, (s, o) in enumerate(zip(stops, total)):
                route_rows.append({"route_code": code + direction, "route_name": name, "sequence": i + 1,
                                   "stop_code": s["code"], "stop_name": s["name"], "lat": s["lat"], "lng": s["lng"],
                                   "offset_minutes": o, "is_major": None, "color": COLORS[ci % len(COLORS)]})
        rows += route_rows
        n_found = sum(1 for k in kind if k == "found")
        need = [f"{n} ({k})" for n, k in zip(r["stops"], kind) if k != "found"]
        length_km = sum(hav((a["lat"], a["lng"]), (b["lat"], b["lng"])) for a, b in zip(seq_codes, seq_codes[1:])) * ROAD_FACTOR / 1000
        report.append(f"| {code} | {r['from']} - {r['to']} | {len(r['stops'])} | {n_found} located, {len(need)} estimated | ~{length_km:.0f} km |")
        if need:
            report.append(f"| | needs checking: {', '.join(need)} | | | |")
    shared = {s["code"] for s in registry if len(s["routes"]) > 1}
    for row in rows:  # major = route ends + interchanges between routes
        same = [x for x in rows if x["route_code"] == row["route_code"]]
        row["is_major"] = 1 if row["stop_code"] in shared or row["sequence"] in (1, len(same)) else 0
    with open(HERE / "pma_routes_import.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    total = sum(stats.values())
    (HERE / "review.md").write_text(
        "# PMA Speedo feeder routes: import review\n\n"
        f"Source: {SRC['_source']}\n\n"
        f"* Routes: {len({r['route_code'] for r in rows})} (each PMA route plus its return direction)\n"
        f"* Distinct stops: {len(registry)}, of which {len(shared)} are shared between routes (interchanges)\n"
        f"* Stop positions: {stats['found']}/{total} matched on OpenStreetMap, "
        f"{stats['interpolated']}/{total} placed between neighbouring stops (no match on the route's line)\n"
        "* Official from PMA: route codes, end points, stop names and order.\n"
        "* Estimated, to verify: stop coordinates, travel minutes between stops, the return direction.\n"
        "* Not published by PMA and NOT included: fares, operating hours, frequencies (add them under Admin > Schedules).\n"
        "* Map data (c) OpenStreetMap contributors, ODbL.\n\n"
        "| Route | Ends (PMA) | Stops | Positions | Length (est.) |\n|---|---|---|---|---|\n" + "\n".join(report) + "\n",
        encoding="utf-8")
    print(f"{len(rows)} rows, {len({r['route_code'] for r in rows})} routes, {len(registry)} stops, positions: {stats}")


if __name__ == "__main__":
    main()
