"""Geometry helpers: distances, polyline chainage and projection."""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_R = 6_371_008.8  # metres


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


@dataclass
class Projection:
    chainage: float       # distance along the line from its start (m)
    offset: float         # perpendicular distance from the line (m)
    lat: float            # snapped point
    lon: float


class Polyline:
    """A route geometry with cumulative distances, supporting snap-to-route."""

    def __init__(self, points: list[tuple[float, float]]):
        if len(points) < 2:
            raise ValueError("a polyline needs at least two points")
        self.points = [(float(a), float(b)) for a, b in points]
        self.cum = [0.0]
        for (a1, o1), (a2, o2) in zip(self.points, self.points[1:]):
            self.cum.append(self.cum[-1] + haversine(a1, o1, a2, o2))

    @property
    def length(self) -> float:
        return self.cum[-1]

    def project(self, lat: float, lon: float, near_chainage: float | None = None, window_m: float = 2000) -> Projection:
        """Snap a point to the line. If `near_chainage` is given, prefer segments near it
        (avoids jumping to the wrong side of routes that double back)."""
        best: Projection | None = None
        best_score = math.inf
        kx = math.cos(math.radians(lat)) * math.pi / 180 * EARTH_R
        ky = math.pi / 180 * EARTH_R
        for i in range(len(self.points) - 1):
            (a1, o1), (a2, o2) = self.points[i], self.points[i + 1]
            # local planar coordinates (metres) relative to the query point
            x1, y1 = (o1 - lon) * kx, (a1 - lat) * ky
            x2, y2 = (o2 - lon) * kx, (a2 - lat) * ky
            dx, dy = x2 - x1, y2 - y1
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg2))
            px, py = x1 + t * dx, y1 + t * dy
            off = math.hypot(px, py)
            seg_len = self.cum[i + 1] - self.cum[i]
            ch = self.cum[i] + t * seg_len
            score = off
            if near_chainage is not None and abs(ch - near_chainage) > window_m:
                score += abs(ch - near_chainage) - window_m  # penalise far-away matches
            if score < best_score:
                best_score = score
                best = Projection(ch, off, a1 + t * (a2 - a1), o1 + t * (o2 - o1))
        assert best is not None
        return best

    def point_at(self, chainage: float) -> tuple[float, float, float]:
        """Return (lat, lon, heading_deg) at a distance along the line."""
        c = max(0.0, min(self.length, chainage))
        for i in range(len(self.cum) - 1):
            if self.cum[i + 1] >= c:
                seg = self.cum[i + 1] - self.cum[i]
                t = 0.0 if seg == 0 else (c - self.cum[i]) / seg
                (a1, o1), (a2, o2) = self.points[i], self.points[i + 1]
                return a1 + t * (a2 - a1), o1 + t * (o2 - o1), bearing(a1, o1, a2, o2)
        a, o = self.points[-1]
        return a, o, 0.0


def in_service_area(lat: float, lon: float, s) -> bool:
    return s.area_min_lat <= lat <= s.area_max_lat and s.area_min_lon <= lon <= s.area_max_lon
