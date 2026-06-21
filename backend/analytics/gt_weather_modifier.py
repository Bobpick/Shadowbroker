"""Weather context for Strategic Risk Analytics — signal noise and collection planning."""

from __future__ import annotations

import logging
from typing import Any

from cachetools import TTLCache

from analytics.region_geo import theater_centroid, theater_from_coords
from services.open_meteo import fetch_point_weather

logger = logging.getLogger(__name__)

_REGION_WEATHER_CACHE: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=64, ttl=1800)

_STORM_CODES = {65, 67, 82, 95, 96, 99}
_SEVERE_PRECIP_CODES = {63, 65, 67, 80, 81, 82, 95, 96, 99}
_FOG_CODES = {45, 48}


def _coords_for_region(region: str, coords: list[float] | None = None) -> tuple[float, float] | None:
    if coords and len(coords) >= 2:
        try:
            return float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            pass
    centroid = theater_centroid(region)
    if centroid:
        return centroid
    return None


def _count_heavy_cloud_hours(hourly: list[dict[str, Any]], *, threshold: float = 70.0) -> int:
    streak = 0
    for row in hourly[:48]:
        cloud = row.get("cloud_cover_pct")
        if cloud is None or float(cloud) >= threshold:
            streak += 1
        else:
            break
    return streak


def assess_weather_context(
    weather: dict[str, Any],
    *,
    region: str = "",
) -> dict[str, Any]:
    """Derive GT signal-noise metrics and collection guidance from Open-Meteo payload."""
    if weather.get("error"):
        return {
            "region": region,
            "weather_noise": 0.0,
            "storm_severity": 0.0,
            "optical_status": "unknown",
            "optical_summary": "Weather unavailable",
            "collection_recommendation": "unknown",
            "collection_badge": "COLLECTION: weather data unavailable",
            "poor_optical_hours": 0,
            "unrest_modifier": 0.0,
            "conflict_modifier": 0.0,
            "gt_note": "",
            "conditions": None,
            "cloud_cover_pct": None,
        }

    current = weather.get("current") or {}
    optical = weather.get("optical_window") or {}
    hourly = weather.get("hourly_next_48h") or []

    code = int(current.get("weather_code") or 0)
    precip = float(current.get("precipitation_mm") or 0.0)
    wind = float(current.get("wind_speed_kmh") or 0.0)
    cloud = current.get("cloud_cover_pct")

    noise = 0.0
    storm = 0.0

    if code in _STORM_CODES:
        storm += 0.45
        noise += 0.35
    elif code in _SEVERE_PRECIP_CODES:
        storm += 0.25
        noise += 0.2
    if code in _FOG_CODES:
        noise += 0.18
    if precip >= 2.0:
        noise += 0.12
        storm += 0.1
    elif precip >= 0.5:
        noise += 0.06
    if wind >= 55:
        noise += 0.15
        storm += 0.1
    elif wind >= 35:
        noise += 0.08

    optical_status = str(optical.get("status") or "unknown")
    if optical_status == "poor":
        noise += 0.22
    elif optical_status == "fair":
        noise += 0.08

    noise = min(1.0, round(noise, 3))
    storm = min(1.0, round(storm, 3))

    poor_hours = _count_heavy_cloud_hours(hourly)
    unrest_mod = round(noise * 0.04, 4)
    conflict_mod = round(noise * 0.025, 4)

    if optical_status == "poor":
        recommendation = "sar_recommended"
        if poor_hours >= 24:
            badge = f"OPTICAL: POOR — SAR RECOMMENDED ({poor_hours}h+ heavy cloud)"
        else:
            badge = "OPTICAL: POOR — SAR RECOMMENDED"
    elif optical_status == "fair":
        recommendation = "optical_limited"
        badge = str(optical.get("summary") or "OPTICAL: LIMITED — check forecast window")
    elif optical_status == "good":
        recommendation = "optical_ok"
        badge = "OPTICAL: CLEAR — Sentinel-2 viable"
    else:
        recommendation = "unknown"
        badge = "COLLECTION: assess local cloud cover"

    gt_note = ""
    if noise >= 0.45:
        gt_note = (
            "Severe weather elevates unrest/conflict signal noise — treat social/OSINT "
            "chatter as potentially weather-contaminated."
        )
    elif noise >= 0.25:
        gt_note = (
            "Active weather may amplify cheap talk; prioritize costly-signal confirmation."
        )

    return {
        "region": region,
        "weather_noise": noise,
        "storm_severity": storm,
        "optical_status": optical_status,
        "optical_summary": optical.get("summary") or "",
        "collection_recommendation": recommendation,
        "collection_badge": badge,
        "poor_optical_hours": poor_hours,
        "unrest_modifier": unrest_mod,
        "conflict_modifier": conflict_mod,
        "gt_note": gt_note,
        "conditions": current.get("conditions"),
        "cloud_cover_pct": cloud,
        "source": weather.get("source") or "Open-Meteo",
    }


def fetch_region_weather(
    region: str,
    coords: list[float] | None = None,
) -> dict[str, Any]:
    """Cached Open-Meteo fetch for a GT region or coordinate pair."""
    region_key = str(region or "global").strip().lower() or "global"
    resolved = _coords_for_region(region_key, coords)
    if resolved is None:
        return {"error": "no_coords"}

    lat, lng = resolved
    cache_key = f"{region_key}:{round(lat, 2)}:{round(lng, 2)}"
    cached = _REGION_WEATHER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    payload = fetch_point_weather(lat, lng)
    _REGION_WEATHER_CACHE[cache_key] = payload
    return payload


def weather_context_for_region(
    region: str,
    coords: list[float] | None = None,
) -> dict[str, Any]:
    weather = fetch_region_weather(region, coords)
    return assess_weather_context(weather, region=region)


def weather_evidence_multiplier(context: dict[str, Any]) -> float:
    """Damp costly-signal evidence during storms — reduces false-positive updates."""
    noise = float(context.get("weather_noise") or 0.0)
    return max(0.55, 1.0 - noise * 0.35)


def enrich_heatmap_with_weather(heatmap: dict[str, Any]) -> dict[str, Any]:
    """Attach weather noise + collection planner fields to GT heatmap features."""
    features = heatmap.get("features") or []
    enriched: list[dict[str, Any]] = []

    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        region = str(props.get("region") or "").strip().lower()
        coords = None
        geometry = feature.get("geometry") or {}
        gcoords = geometry.get("coordinates")
        if isinstance(gcoords, (list, tuple)) and len(gcoords) >= 2:
            try:
                lng, lat = float(gcoords[0]), float(gcoords[1])
                coords = [lat, lng]
            except (TypeError, ValueError):
                coords = None

        if region and coords and theater_from_coords(coords[0], coords[1]):
            region = theater_from_coords(coords[0], coords[1]) or region

        context = weather_context_for_region(region, coords)
        props["weather_noise"] = context.get("weather_noise", 0.0)
        props["storm_severity"] = context.get("storm_severity", 0.0)
        props["optical_status"] = context.get("optical_status")
        props["collection_planner"] = context.get("collection_recommendation")
        props["collection_badge"] = context.get("collection_badge")
        props["weather_summary"] = context.get("optical_summary") or context.get("conditions")
        props["poor_optical_hours"] = context.get("poor_optical_hours", 0)

        if context.get("gt_note"):
            base_interp = str(props.get("interpretation") or "")
            note = str(context["gt_note"])
            props["interpretation"] = f"{base_interp} {note}".strip() if base_interp else note

        unrest = float(props.get("unrest") or 0.0)
        conflict = float(props.get("conflict") or 0.0)
        props["unrest_weather_adj"] = round(
            min(0.99, unrest + float(context.get("unrest_modifier") or 0.0)),
            4,
        )
        props["conflict_weather_adj"] = round(
            min(0.99, conflict + float(context.get("conflict_modifier") or 0.0)),
            4,
        )

        enriched.append({**feature, "properties": props})

    return {**heatmap, "features": enriched, "weather_enriched": True}


def clear_weather_cache() -> None:
    """Test helper — reset cached theater weather."""
    _REGION_WEATHER_CACHE.clear()