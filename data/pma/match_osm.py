"""Match PMA stop names to named places in an OpenStreetMap extract of Lahore (osm_lahore_named_places.json).

Writes geocode_candidates.json: stop name -> up to 5 candidate places, best first. build_import.py then picks,
per route, the candidates that keep the route short and straight. Data (c) OpenStreetMap contributors, ODbL.
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from geocode_stops import clean

HERE = Path(__file__).parent
PLACES = json.loads((HERE / "osm_lahore_named_places.json").read_text(encoding="utf-8"))
ROUTES = json.loads((HERE / "pma_routes_2026-11-19.json").read_text(encoding="utf-8"))["routes"]
OUT = HERE / "geocode_candidates.json"

SPELLING = {"morr": "mor", "more": "mor", "collage": "college", "shahdra": "shahdara", "gajjumatta": "gajumata",
            "gajjumata": "gajumata", "chuburji": "chauburji", "naizi": "niazi", "goal": "gol", "chaker": "chakar",
            "hajwery": "hajveri", "quid": "quaid", "haily": "hailey", "amer": "amar", "kotlakhpat": "kot lakhpat",
            "phattak": "phatak", "nursary": "nursery", "akber": "akbar", "ichara": "ichhra", "gymkhana": "gymkhana",
            "mcdonalds": "mcdonald", "centre": "center", "pully": "pull", "pully": "pull", "shoukat": "shaukat",
            "dying": "dyeing", "baigum": "begum", "javaid": "javed", "lidher": "lidhar", "wandala": "wandala",
            "hanjarwal": "hanjarwal", "naqsha": "naqsha", "heir": "hair", "karbath": "karbath", "texali": "taxali", "chungi": "chungi"}
GENERIC = {"stop", "bus", "road", "chowk", "mor", "market", "hospital", "station", "colony", "town", "block", "gate",
           "no", "the", "of", "lahore", "society", "pull", "college", "school", "adda", "metro", "main", "new", "old",
           "park", "number", "stadium", "center", "railway", "and", "e", "ul", "ud", "din", "di", "1", "2", "3", "4", "5"}
PREFERRED = ("highway=bus_stop", "public_transport", "junction", "place=", "highway=traffic_signals", "railway=station",
             "amenity=bus_station", "landuse=residential")


def norm(s: str) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(SPELLING.get(t, t) for t in s.split())


def tokens(s: str) -> set[str]:
    return set(norm(s).split())


index: dict[str, set[int]] = {}
pnames = []
for i, p in enumerate(PLACES):
    ns = [norm(n) for n in p["names"] if n]
    pnames.append(ns)
    for n in ns:
        for t in n.split():
            index.setdefault(t, set()).add(i)


def score(stop: str, place_name: str) -> float:
    a, b = norm(stop), place_name
    if not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    key = ta - GENERIC or ta
    cover = len(key & tb) / len(key)  # share of the stop name's distinctive words found in the place name
    return max(ratio, 0.55 * ratio + 0.45 * cover) if cover else ratio * 0.8


def candidates(stop: str) -> list[dict]:
    ta = tokens(stop)
    key = ta - GENERIC or ta
    pool = set()
    for t in key:
        pool |= index.get(t, set())
    scored = []
    for i in pool:
        s = max((score(stop, n) for n in pnames[i]), default=0)
        if s >= 0.72:
            bonus = 0.05 if PLACES[i]["kind"].startswith(PREFERRED) else 0.0
            scored.append((s + bonus, i))
    scored.sort(reverse=True)
    out = []
    for s, i in scored:
        p = PLACES[i]
        if any(abs(p["lat"] - q["lat"]) < 0.0015 and abs(p["lng"] - q["lng"]) < 0.0015 for q in out):
            continue  # same spot already listed
        out.append({"lat": p["lat"], "lng": p["lng"], "match": "; ".join(p["names"])[:100], "type": p["kind"],
                    "score": round(s, 2), "source": "osm-extract"})
        if len(out) == 5:
            break
    return out


def main():
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    names = sorted({clean(s) for r in ROUTES.values() for s in r["stops"]})
    result = {}
    for n in names:
        c = candidates(n)
        for extra in previous.get(n) or []:  # keep Nominatim answers fetched earlier as further options
            if all(abs(extra["lat"] - q["lat"]) > 0.0015 or abs(extra["lng"] - q["lng"]) > 0.0015 for q in c):
                c.append(extra | {"source": "nominatim"})
        result[n] = c[:6]
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(1 for v in result.values() if v)}/{len(names)} stop names have at least one candidate")


if __name__ == "__main__":
    main()
