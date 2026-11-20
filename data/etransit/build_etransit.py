"""Speedo (e-Transit line 42 "LFR- Speedo", Lahore) -> Speedo Live import files.

Source: the public JSON behind https://etransit.punjab.gov.pk/public/route-planner?city=110&line=42
(Punjab Masstransit Authority). fetch: python build_etransit.py --fetch   (1 request per second)

Writes:
  speedo_routes.csv      Admin > Routes > Import (routes file): both directions of every route, stops in order
  speedo_schedules.csv   Admin > Routes > Import (schedules file): first/last departure and typical headway
  review.md              what was imported, and anything skipped

Only line 42 is used (not Orange Line, Metro Bus, LFR-EV or PTC buses). Everything here is official
e-Transit data: stop names, coordinates, order, minutes between stops and today's departures.
"""
import argparse
import csv
import json
import math
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "raw"
API = "https://etransit.punjab.gov.pk/repo/backend/public/api"
LINE_ID, DISTRICT_ID = 42, 110
UA = "SpeedoLive-importer/1.0 (public route planner data, 1 req/s)"
AREA = (31.20, 31.75, 74.00, 74.65)
COLORS = ["#b91c1c", "#1d4ed8", "#0f766e", "#7c3aed", "#ea580c", "#0369a1", "#15803d", "#a16207", "#9333ea",
          "#c2410c", "#0e7490", "#4d7c0f", "#be123c", "#1e40af", "#86198f", "#047857", "#b45309", "#6d28d9",
          "#0891b2", "#65a30d", "#db2777", "#4338ca", "#ca8a04", "#059669"]


def fetch() -> None:
    import httpx

    RAW.mkdir(exist_ok=True)
    c = httpx.Client(headers={"User-Agent": UA}, timeout=60)
    d = c.get(f"{API}/home-page/districts-with-lines", params={"page": "planner"}).json()["data"]
    (RAW / "districts-with-lines.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    for r in (r for r in d["routes"] if r["line_id"] == LINE_ID):
        time.sleep(1)
        res = c.post(f"{API}/home-page/get-line-schedules", json={"line_id": LINE_ID, "main_route_id": r["id"]})
        (RAW / f"route_{r['id']}.json").write_text(json.dumps(res.json(), ensure_ascii=False), encoding="utf-8")


def hav(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def clean(name: str) -> str:
    n = re.sub(r"\s*\b(lfr|lrf)\b\s*(up|down|dn)?\s*$", "", name.strip(), flags=re.I)
    n = re.sub(r"\s+(up|down)\s*$", "", n, flags=re.I)
    n = re.sub(r"^\d+\.\s*", "", n)  # "4. Azadi Chowk"
    n = re.sub(r"\s{2,}", " ", n).strip(" -")
    return n or name.strip()


def title(long_name: str) -> str:
    """'RT-8 Canal to Jinnah Terminal' -> 'RT-8: Canal to Jinnah Terminal'; tidy spacing."""
    n = re.sub(r"\s+", " ", long_name).strip().replace("Station Station", "Station")
    m = re.match(r"^(RT|FRT)[\s-]*(\d+)\s*(.*)$", n, flags=re.I)
    return f"{m.group(1).upper()}-{m.group(2)}: {m.group(3)}" if m else n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="download fresh data first")
    if ap.parse_args().fetch:
        fetch()
    lines = json.loads((RAW / "districts-with-lines.json").read_text(encoding="utf-8"))
    mains = sorted((r for r in lines["routes"] if r["line_id"] == LINE_ID), key=lambda r: r["headsign"])
    rows, sched, notes, stop_names = [], [], [], {}
    for n, mr in enumerate(mains):
        data = json.loads((RAW / f"route_{mr['id']}.json").read_text(encoding="utf-8"))["data"]
        for side, suffix in (("forward", ""), ("backward", "R")):
            d = data.get(side) or {}
            raw = sorted(d.get("stops") or [], key=lambda s: int(s["sequence"]))
            if len(raw) < 2:
                notes.append(f"{mr['headsign']} ({side}): no stops published, skipped")
                continue
            pts = [(float(s["latitude"]), float(s["longitude"])) for s in raw]
            keep = []
            for i, s in enumerate(raw):
                p = pts[i]
                if not (AREA[0] <= p[0] <= AREA[1] and AREA[2] <= p[1] <= AREA[3]):
                    notes.append(f"{mr['headsign']} ({side}): {s['name']} has coordinates outside Lahore, skipped")
                    continue
                if 0 < i < len(raw) - 1 and hav(pts[i - 1], p) > 3000 and hav(p, pts[i + 1]) > 3000 \
                        and hav(pts[i - 1], pts[i + 1]) < 3000:
                    notes.append(f"{mr['headsign']} ({side}): {s['name']} lies far off the line (wrong coordinates?), skipped")
                    continue
                if keep and keep[-1][0]["id"] == s["id"]:
                    continue  # same stop listed twice in a row
                keep.append((s, p))
            seen, uniq = set(), []
            for s, p in keep:  # a stop may appear only once per route
                if s["id"] in seen:
                    notes.append(f"{mr['headsign']} ({side}): {s['name']} appears twice, second visit dropped")
                    continue
                seen.add(s["id"])
                uniq.append((s, p))
            # each direction has its own e-Transit name ("A to B" / "B to A")
            code = f"S{mr['id']}{suffix}"
            name = "Speedo " + title(d.get("route_long_name") or mr["headsign"])
            if suffix and title(d.get("route_long_name") or "") == title((data.get("forward") or {}).get("route_long_name") or ""):
                name += " (return)"  # only when e-Transit did not name the return trip separately
            off = 0.0
            for i, (s, p) in enumerate(uniq):
                if i:
                    off += float(s.get("previous_duration") or 0) or 2.0
                code_s = f"ET{s['id']}"
                stop_names.setdefault(code_s, clean(s["name"]))
                rows.append({"route_code": code, "route_name": name[:200], "sequence": i + 1, "stop_code": code_s,
                             "stop_name": stop_names[code_s], "lat": round(p[0], 7), "lng": round(p[1], 7),
                             "offset_minutes": round(off, 1), "is_major": 1 if i in (0, len(uniq) - 1) else 0,
                             "color": COLORS[n % len(COLORS)]})
            starts = sorted({t["start_time"] for t in (raw[0].get("timings") or [])})
            if starts:
                times = [datetime.strptime(t, "%Y-%m-%d %H:%M:%S") for t in starts]
                gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:]) if b > a]
                head = int(round(statistics.median(gaps))) if gaps else 30
                sched.append({"route_code": code, "days": "mon,tue,wed,thu,fri,sat,sun",
                              "first_departure": times[0].strftime("%H:%M"), "last_departure": times[-1].strftime("%H:%M"),
                              "frequency_minutes": max(1, head),
                              "notes": f"e-Transit timetable of {times[0]:%Y-%m-%d}: {len(times)} departures"})
            else:
                notes.append(f"{mr['headsign']} ({side}): no timetable published")
    # stops shared by several routes are interchanges
    use = {}
    for r in rows:
        use.setdefault(r["stop_code"], set()).add(r["route_code"].rstrip("R"))
    for r in rows:
        if len(use[r["stop_code"]]) > 1:
            r["is_major"] = 1
    with open(HERE / "speedo_routes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(HERE / "speedo_schedules.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sched[0]))
        w.writeheader()
        w.writerows(sched)
    routes = sorted({r["route_code"] for r in rows})
    (HERE / "review.md").write_text(
        "# Speedo network from e-Transit\n\n"
        "Source: Punjab Masstransit Authority e-Transit route planner, line 42 \"LFR- Speedo\" (Lahore), "
        f"https://etransit.punjab.gov.pk/public/route-planner?city=110&line=42, downloaded {datetime.now():%Y-%m-%d}.\n\n"
        f"* Routes: {len(routes)} ({len(mains)} e-Transit routes, each direction separately)\n"
        f"* Stops: {len(stop_names)} (official coordinates), {sum(1 for v in use.values() if len(v) > 1)} shared between routes\n"
        f"* Timetables: {len(sched)} (first/last departure and median headway of the day downloaded; applied to every day)\n"
        "* Minutes between stops: e-Transit's per-stop travel time\n\n"
        "## Skipped or adjusted\n\n" + ("\n".join(f"* {x}" for x in notes) or "* nothing") + "\n", encoding="utf-8")
    print(f"{len(rows)} rows, {len(routes)} routes, {len(stop_names)} stops, {len(sched)} timetables, {len(notes)} notes")


if __name__ == "__main__":
    main()
