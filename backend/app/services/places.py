"""Find any place in Lahore by name (markets, hospitals, neighbourhoods...) with OpenStreetMap Nominatim.

Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/): at most 1 request per second
for the whole app, an identifying User-Agent, cache results, and no search-as-you-type. The web app therefore only
calls this when the passenger presses Search; results are cached in memory for a day.
Place data (c) OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

import httpx

from ..config import get_settings

log = logging.getLogger("speedo.places")
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "SpeedoLive/1.0 (Lahore bus route planner; on-demand place search)"
CACHE_SECONDS = 24 * 3600
_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_lock = threading.Lock()
_last_call = 0.0


def _short(display_name: str) -> str:
    parts = [p.strip() for p in display_name.split(",") if p.strip()]
    keep = [p for p in parts if p not in ("Lahore", "Lahore District", "Lahore Division", "Punjab", "Pakistan")
            and not p.isdigit()]
    return ", ".join(keep[:3]) or parts[0]


def fetch(q: str) -> list[dict]:
    """Ask Nominatim (rate limited to 1 request/second across the app). Returns [] on any failure."""
    global _last_call
    s = get_settings()
    viewbox = f"{s.area_min_lng},{s.area_max_lat},{s.area_max_lng},{s.area_min_lat}"
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            r = httpx.get(NOMINATIM, params={"q": q, "format": "jsonv2", "limit": 6, "viewbox": viewbox, "bounded": 1,
                                             "countrycodes": "pk", "accept-language": "en"},
                          headers={"User-Agent": UA}, timeout=8)
            r.raise_for_status()
            rows = r.json()
        except Exception as exc:  # the planner still works with stop names
            log.warning("place search failed (query of %d characters): %s", len(q), type(exc).__name__)
            return []
    return [{"label": _short(x.get("display_name", "")), "detail": x.get("display_name", ""), "lat": float(x["lat"]),
             "lng": float(x["lon"]), "kind": "place", "type": f'{x.get("category")}/{x.get("type")}'} for x in rows]


def search(q: str) -> list[dict]:
    key = " ".join(q.lower().split())
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        _cache.move_to_end(key)
        return hit[1]
    rows = fetch(q)
    _cache[key] = (now, rows)
    while len(_cache) > 1000:
        _cache.popitem(last=False)
    return rows
