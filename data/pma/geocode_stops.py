"""Look up approximate coordinates for the PMA stop names with OpenStreetMap Nominatim.

Usage policy (https://operations.osmfoundation.org/policies/nominatim/): at most 1 request per second,
an identifying User-Agent, results cached so each name is asked once. Data (c) OpenStreetMap contributors, ODbL.
Results are approximate: a stop name often matches a nearby landmark, not the exact bus stop.
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
SRC = HERE / "pma_routes_2026-11-19.json"
CACHE = HERE / "geocode_candidates.json"  # name -> list of up to 5 candidate places
UA = "SpeedoLive-stop-geocoding/1.0 (one-off, cached; Lahore feeder bus stops)"
VIEWBOX = "74.05,31.75,74.65,31.20"  # lon_left,lat_top,lon_right,lat_bottom (Lahore district)


def clean(name: str) -> str:
    n = re.sub(r"\s*[-]?\s*\b(Stop\s*)?\d+$", "", name.strip())  # "Stop 1", "-2", " 1"
    n = re.sub(r"\bStop\b|\bBus Stop\b", "", n, flags=re.I)
    n = n.replace("Morr", "Mor").replace("Collage", "College").replace("Stationi", "Station")
    return re.sub(r"\s+", " ", n).strip(" -") or name


def main() -> None:
    routes = json.loads(SRC.read_text(encoding="utf-8"))["routes"]
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    names = sorted({clean(s) for r in routes.values() for s in r["stops"]})
    todo = [n for n in names if n not in cache]
    print(f"{len(names)} distinct names, {len(todo)} to look up", flush=True)
    with httpx.Client(headers={"User-Agent": UA}, timeout=30) as c:
        for i, n in enumerate(todo, 1):
            hits = []
            for q in (f"{n}, Lahore", n):
                try:
                    r = c.get("https://nominatim.openstreetmap.org/search",
                              params={"q": q, "format": "jsonv2", "limit": 5, "viewbox": VIEWBOX, "bounded": 1,
                                      "countrycodes": "pk"})
                    r.raise_for_status()
                    res = r.json()
                except Exception as exc:
                    print(f"  ! {n}: {exc}", flush=True)
                    res = []
                time.sleep(1.1)
                for x in res:
                    hits.append({"lat": float(x["lat"]), "lng": float(x["lon"]), "match": x.get("display_name", "")[:120],
                                 "type": f'{x.get("category")}/{x.get("type")}', "query": q})
                if res:
                    break
            cache[n] = hits
            CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} done, found {sum(1 for v in cache.values() if v)}", flush=True)
    print(f"finished: {sum(1 for n in names if cache.get(n))}/{len(names)} names found", flush=True)


if __name__ == "__main__":
    sys.exit(main())
