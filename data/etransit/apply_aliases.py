"""Other names of Speedo stops, from the official e-Transit data (line 42 "LFR- Speedo" only).

e-Transit lists the same stop under several spellings (forward / backward direction, older names):
"Chungi Amar Sidhu" / "Chungi Amer Sidhu", "Atari Saroba" / "Attari Saroba", "Kachehry" / "Zila Katchery".
Passengers search and speak those spellings too, so each app stop gets them as `aliases`.

Rules (nothing is invented; every alias is a name e-Transit itself uses):
- names of the same e-Transit stop (app stop code ET<id>), plus names of e-Transit stops within 60 m that sound
  alike (consonant-skeleton similarity >= 0.75: wrong coordinates sometimes put a different stop nearby);
- tidied: "Lfr Up/Down", "Lmbs", "Station", "Stop", direction tags and numbering removed;
- dropped when it only differs by such words, by numbering, or is part of the stop's own name (search finds those).

    cd backend
    .venv\\Scripts\\python ..\\data\\etransit\\apply_aliases.py            # writes stop_aliases.json (review it)
    .venv\\Scripts\\python ..\\data\\etransit\\apply_aliases.py --apply    # also saves the aliases in Firestore

Uses the downloaded raw/route_*.json (see build_etransit.py --fetch).
"""
import argparse
import difflib
import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
sys.path.insert(0, str(HERE))

from build_etransit import clean, hav  # noqa: E402

NEAR_M = 60
SIMILAR = 0.75
OUT = HERE / "stop_aliases.json"


def tidy(name: str) -> str:
    n = clean(name)
    n = re.sub(r"\((forward|backward|fwd|bwd)\)", " ", n, flags=re.I)
    n = re.sub(r"\b(station|stop|lmbs|down|up|dn)\b", " ", n, flags=re.I)
    n = re.sub(r"\s+\d+$", "", n)
    return re.sub(r"\s{2,}", " ", n).strip(" -.,")


def key(name: str) -> str:
    """What is left of a name once numbering, direction tags and generic words are removed (spaces too)."""
    n = re.sub(r"^\s*\d+[.)]?\s*", "", name.lower())
    n = re.sub(r"\((forward|backward|fwd|bwd)\)", " ", n)
    n = re.sub(r"\b(station|stop|bus|lmbs|no|north|south|east|west)\b", " ", n)
    return re.sub(r"[^a-z]+", "", n)


def raw_stops() -> dict[int, dict]:
    raw: dict[int, dict] = {}
    for f in glob.glob(str(HERE / "raw" / "route_*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))["data"]
        for side in ("forward", "backward"):
            for s in (d.get(side) or {}).get("stops", []):
                raw.setdefault(int(s["id"]), {"names": set(), "pt": (float(s["latitude"]), float(s["longitude"]))})
                raw[int(s["id"])]["names"].add(s["name"])
    return raw


def build(stops: list[dict]) -> dict[str, dict]:
    """stops: [{code, name, lat, lng}] of the app -> {code: {name, aliases}} for stops that have other names."""
    from app.services.textmatch import skeleton

    raw = raw_stops()
    out = {}
    for s in stops:
        if not s["code"].startswith("ET"):
            continue
        et_id, pt, own = int(s["code"][2:]), (s["lat"], s["lng"]), key(s["name"])
        found: dict[str, str] = {}
        for rid, r in raw.items():
            same = rid == et_id
            if not same and hav(pt, r["pt"]) > NEAR_M:
                continue
            for n in r["names"]:
                t = tidy(n)
                k = key(t)
                if len(k) < 3 or k in own or own in k:
                    continue
                if not same and difflib.SequenceMatcher(None, skeleton(t), skeleton(s["name"])).ratio() < SIMILAR:
                    continue
                found.setdefault(k, t)  # one spelling per distinct name
        if found:
            out[s["code"]] = {"name": s["name"], "aliases": sorted(found.values(), key=str.lower)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="save the aliases on the stops in Firestore")
    args = ap.parse_args()
    from app import firebase
    from app.db import SessionLocal
    from app.models import BusStop

    firebase.init()
    with SessionLocal() as db:
        stops = db.all(BusStop)
        result = build([{"code": s.code, "name": s.name, "lat": s.lat, "lng": s.lng} for s in stops])
        OUT.write_text(json.dumps({"source": "PMA e-Transit route planner, line 42 LFR- Speedo "
                                             "(https://etransit.punjab.gov.pk/public/route-planner?city=110&line=42)",
                                   "stops": result}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(result)} of {len(stops)} stops have other names -> {OUT.name}")
        if not args.apply:
            print("dry run: nothing saved (add --apply)")
            return
        changed = 0
        for s in stops:
            new = result.get(s.code, {}).get("aliases", [])
            if list(s.aliases or []) != new:
                s.aliases = new
                changed += 1
        db.commit()
        print(f"saved aliases on {changed} stops")


if __name__ == "__main__":
    main()
