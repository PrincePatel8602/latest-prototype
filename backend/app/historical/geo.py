"""Small deterministic geometry helpers (no external deps)."""
from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

# COARSE Gulf of Mexico polygon as (lon, lat). It is an approximation used only to flag
# "observation inside the Gulf region"; it includes adjacent coastal water/land and is NOT
# a legal or hydrographic boundary. Stored results say so (see GULF_POLYGON_NOTE).
GULF_POLYGON: tuple[tuple[float, float], ...] = (
    (-97.8, 21.5), (-97.5, 26.0), (-97.2, 27.8), (-94.0, 29.4), (-90.0, 29.2),
    (-89.0, 30.3), (-85.5, 30.0), (-84.0, 30.0), (-82.8, 28.5), (-81.8, 26.0),
    (-81.0, 24.6), (-83.5, 23.6), (-85.0, 22.0), (-86.6, 21.4), (-87.2, 21.6),
    (-90.5, 21.2), (-91.8, 18.6), (-94.5, 18.2), (-96.0, 19.0),
)
GULF_POLYGON_NOTE = "approximate Gulf of Mexico polygon (coarse; includes adjacent coastal areas)"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def point_in_polygon(lon: float, lat: float, polygon=GULF_POLYGON) -> bool:
    """Ray-casting point-in-polygon (lon = x, lat = y)."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_gulf(lat: float, lon: float) -> bool:
    return point_in_polygon(lon, lat)
