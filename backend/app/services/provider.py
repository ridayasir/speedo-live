"""REAL-WORLD MODE: adapter for an authorised third-party GPS feed (e.g. on-board trackers).

Set GPS_SOURCE=provider, GPS_PROVIDER_URL and GPS_PROVIDER_TOKEN once an operator grants
access. The feed must return JSON:

    [{"device_id": "...", "lat": 31.5, "lon": 74.3, "speed_mps": 6.1, "heading": 90,
      "accuracy_m": 8, "recorded_at": "2026-11-04T10:00:00Z"}, ...]

Devices are matched to buses by `buses.gps_device_id`. Adapt `fetch()` to the real
provider's format; everything after it (validation, storage, ETA, broadcast) is shared
with the driver app. Never point this at a system you are not authorised to use.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from ..config import settings
from ..db import get_db
from .network import network
from .tracking import active_trip, ingest_points, start_trip

log = logging.getLogger("speedo.provider")


def fetch() -> list[dict]:
    req = urllib.request.Request(settings.gps_provider_url, headers={
        "Authorization": f"Bearer {settings.gps_provider_token}" if settings.gps_provider_token else "",
        "Accept": "application/json", "User-Agent": "SpeedoLive/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _infer_direction(route, lat: float, lon: float) -> str:
    p = route.polyline.project(lat, lon)
    return "outbound" if p.chainage < route.length / 2 else "inbound"


def poll_once(feed: list[dict] | None = None) -> dict:
    feed = fetch() if feed is None else feed
    db = get_db()
    stats = {"received": len(feed), "matched": 0, "accepted": 0, "unknown_devices": 0}
    for fix in feed:
        bus = db.one("SELECT * FROM buses WHERE gps_device_id = ? AND status = 'active'", (str(fix.get("device_id")),))
        if not bus:
            stats["unknown_devices"] += 1
            continue
        route = network.get(bus["route_id"])
        if not route or not route.polyline:
            continue
        stats["matched"] += 1
        trip = active_trip(bus["id"])
        if not trip:
            trip = start_trip(bus["id"], None, _infer_direction(route, fix["lat"], fix["lon"]), "provider")
        point = {k: fix.get(k) for k in ("lat", "lon", "speed_mps", "heading", "accuracy_m", "recorded_at")}
        try:
            res = ingest_points(bus["id"], trip["id"], [point], source="provider")
            stats["accepted"] += res["accepted"]
        except Exception as e:
            log.warning("provider fix rejected for %s: %s", bus["bus_number"], e)
    return stats
