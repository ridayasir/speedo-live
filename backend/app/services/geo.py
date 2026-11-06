"""Pure geometry helpers (no database). Coordinates are (lat, lng) in degrees."""
import math
from dataclasses import dataclass

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def point_wkt(lat: float, lng: float) -> str:
    return f"SRID=4326;POINT({lng} {lat})"


def line_wkt(path: list[list[float]]) -> str | None:
    if len(path) < 2:
        return None
    return "SRID=4326;LINESTRING(" + ", ".join(f"{p[1]} {p[0]}" for p in path) + ")"


def cumulative_lengths(path: list[list[float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(path, path[1:]):
        out.append(out[-1] + haversine_m(a[0], a[1], b[0], b[1]))
    return out


def _to_xy(lat: float, lng: float, ref_lat: float) -> tuple[float, float]:
    # local equirectangular projection, accurate to well under 1% across a city
    k = math.cos(math.radians(ref_lat))
    return (math.radians(lng) * EARTH_R * k, math.radians(lat) * EARTH_R)


@dataclass
class Projection:
    distance_along_m: float  # distance from path start to the projected point
    offset_m: float  # perpendicular distance from the path
    lat: float
    lng: float


def project_onto_path(lat: float, lng: float, path: list[list[float]], cum: list[float] | None = None,
                      hint_m: float | None = None, window_m: float = 3000.0) -> Projection:
    """Snap a point to the nearest location on the polyline.

    `hint_m` (previous progress) restricts the search to a window so a route that doubles back
    on itself does not make the bus jump to the wrong side.
    """
    if not path:
        return Projection(0.0, 0.0, lat, lng)
    if len(path) == 1:
        return Projection(0.0, haversine_m(lat, lng, path[0][0], path[0][1]), path[0][0], path[0][1])
    cum = cum or cumulative_lengths(path)
    px, py = _to_xy(lat, lng, lat)
    best: Projection | None = None
    for i in range(len(path) - 1):
        if hint_m is not None and (cum[i + 1] < hint_m - window_m or cum[i] > hint_m + window_m):
            continue
        a, b = path[i], path[i + 1]
        ax, ay = _to_xy(a[0], a[1], lat)
        bx, by = _to_xy(b[0], b[1], lat)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        qx, qy = ax + t * dx, ay + t * dy
        off = math.hypot(px - qx, py - qy)
        if best is None or off < best.offset_m:
            best = Projection(
                distance_along_m=cum[i] + t * (cum[i + 1] - cum[i]),
                offset_m=off,
                lat=a[0] + t * (b[0] - a[0]),
                lng=a[1] + t * (b[1] - a[1]),
            )
    if best is None:  # hint window excluded everything
        return project_onto_path(lat, lng, path, cum)
    return best


def point_at_distance(path: list[list[float]], cum: list[float], d: float) -> tuple[float, float, float]:
    """Return (lat, lng, heading_deg) at distance d along the path."""
    if d <= 0:
        i = 0
    elif d >= cum[-1]:
        a, b = path[-2], path[-1]
        return b[0], b[1], bearing_deg(a[0], a[1], b[0], b[1])
    else:
        i = next(k for k in range(len(cum) - 1) if cum[k + 1] >= d)
    a, b = path[i], path[i + 1]
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg == 0 else (d - cum[i]) / seg
    t = max(0.0, min(1.0, t))
    return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), bearing_deg(a[0], a[1], b[0], b[1])


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
