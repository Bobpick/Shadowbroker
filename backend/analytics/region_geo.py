"""Geographic normalization for GT regions — theaters, centroids, alert spacing."""

from __future__ import annotations

import math
import re
from typing import Any

# name, lat_min, lat_max, lng_min, lng_max, centroid_lat, centroid_lng
# Ordered most-specific first so overlapping boxes resolve predictably.
_THEATER_BBOXES: tuple[tuple[str, float, float, float, float, float, float], ...] = (
    ("gaza", 31.15, 31.65, 34.15, 34.65, 31.50, 34.47),
    ("israel", 29.40, 33.60, 34.10, 35.95, 31.77, 35.22),
    ("taiwan", 21.50, 25.60, 119.30, 122.10, 23.70, 121.00),
    ("ukraine", 44.00, 52.60, 22.00, 40.60, 48.38, 31.17),
    ("syria", 32.00, 37.60, 35.50, 42.40, 33.51, 36.29),
    ("iran", 25.00, 40.00, 44.00, 63.50, 32.43, 53.69),
    ("russia", 41.00, 82.00, 19.00, 180.00, 55.75, 37.62),
    ("china", 18.00, 53.60, 73.00, 135.00, 39.90, 116.40),
)

_THEATER_LABELS = {
    "ukraine": "Ukraine",
    "russia": "Russia",
    "israel": "Israel",
    "gaza": "Gaza",
    "iran": "Iran",
    "syria": "Syria",
    "taiwan": "Taiwan",
    "china": "China",
    "global": "Global",
}

_COORD_REGION_RE = re.compile(r"^-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?$")


def theater_label(region: str) -> str:
    key = str(region or "").strip().lower()
    if key in _THEATER_LABELS:
        return _THEATER_LABELS[key]
    if _COORD_REGION_RE.match(key):
        parts = [piece.strip() for piece in key.split(",") if piece.strip()]
        if len(parts) >= 2:
            try:
                lat = float(parts[0])
                lng = float(parts[-1])
                return f"{lat:.1f}°, {lng:.1f}°"
            except ValueError:
                pass
    return key.replace("_", " ").title()


def theater_from_coords(lat: float, lng: float) -> str | None:
    for name, lat_min, lat_max, lng_min, lng_max, _clat, _clng in _THEATER_BBOXES:
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return name
    return None


def theater_centroid(region: str) -> tuple[float, float] | None:
    key = str(region or "").strip().lower()
    for name, _a, _b, _c, _d, clat, clng in _THEATER_BBOXES:
        if name == key:
            return clat, clng
    return None


def resolve_region_from_coords(lat: float, lng: float, *, precision: int = 1) -> str:
    """Map coordinates to a named theater when possible, else a coarse grid cell."""
    theater = theater_from_coords(lat, lng)
    if theater:
        return theater
    return f"{lat:.{precision}f},{lng:.{precision}f}"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(min(1.0, a)))


def diversify_alerts_by_distance(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    min_separation_km: float = 160.0,
) -> list[dict[str, Any]]:
    """
    Pick top alerts with geographic spread so one theater does not fill the strip.

    Rows must already be risk-sorted. Adds ``nearby_count`` when multiple source
    rows fell within ``min_separation_km`` of the chosen representative.
    """
    if not rows:
        return []

    selected: list[dict[str, Any]] = []
    used_indices: set[int] = set()

    for idx, row in enumerate(rows):
        if len(selected) >= limit:
            break
        lat = float(row.get("lat") or 0.0)
        lng = float(row.get("lng") or 0.0)
        if any(
            haversine_km(lat, lng, float(pick.get("lat") or 0.0), float(pick.get("lng") or 0.0))
            < min_separation_km
            for pick in selected
        ):
            continue
        nearby = 1
        for j, other in enumerate(rows):
            if j == idx:
                continue
            olat = float(other.get("lat") or 0.0)
            olng = float(other.get("lng") or 0.0)
            if haversine_km(lat, lng, olat, olng) < min_separation_km:
                nearby += 1
        enriched = dict(row)
        if nearby > 1:
            enriched["nearby_count"] = nearby
        selected.append(enriched)
        used_indices.add(idx)

    if len(selected) < limit:
        for idx, row in enumerate(rows):
            if idx in used_indices:
                continue
            selected.append(dict(row))
            used_indices.add(idx)
            if len(selected) >= limit:
                break

    return selected[:limit]