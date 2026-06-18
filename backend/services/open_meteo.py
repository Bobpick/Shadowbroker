"""Point weather and cloud-cover forecasts via Open-Meteo (no API key)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from cachetools import TTLCache
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

# 0.1° grid ≈ 11 km — matches dossier cache granularity
_weather_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=800, ttl=1800)

_WMO_LABELS: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def weather_code_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WMO_LABELS.get(int(code), f"Code {int(code)}")


def _optical_window(hourly: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess optical satellite visibility from hourly cloud cover (next 48h)."""
    if not hourly:
        return {
            "status": "unknown",
            "summary": "Forecast unavailable",
            "cloud_now_pct": None,
            "best_window_start": None,
            "best_window_end": None,
        }

    now_cloud = hourly[0].get("cloud_cover_pct")
    blocks: list[tuple[str, str, float]] = []
    block_start: str | None = None
    block_end: str | None = None
    block_vals: list[float] = []

    def flush_block() -> None:
        nonlocal block_start, block_end, block_vals
        if block_start and block_end and block_vals:
            blocks.append((block_start, block_end, sum(block_vals) / len(block_vals)))
        block_start = None
        block_end = None
        block_vals = []

    for row in hourly[:48]:
        cloud = row.get("cloud_cover_pct")
        if cloud is None:
            flush_block()
            continue
        if cloud < 30:
            if block_start is None:
                block_start = row["time"]
            block_end = row["time"]
            block_vals.append(float(cloud))
        else:
            flush_block()
    flush_block()

    best = min(blocks, key=lambda b: b[2], default=None)
    if now_cloud is not None and now_cloud < 30:
        status = "good"
        summary = f"Optical window open — {now_cloud:.0f}% cloud cover now"
    elif best:
        status = "fair"
        avg = best[2]
        start = best[0][:16].replace("T", " ")
        end = best[1][:16].replace("T", " ")
        summary = (
            f"Cloudy now ({now_cloud:.0f}%)" if now_cloud is not None else "Cloudy now"
        ) + f"; clearest window {start}–{end} UTC (avg {avg:.0f}% clouds)"
    else:
        status = "poor"
        summary = (
            f"Heavy cloud cover ({now_cloud:.0f}%) — optical sat likely blind for 48h"
            if now_cloud is not None
            else "Heavy cloud cover — optical sat likely blind for 48h"
        )

    return {
        "status": status,
        "summary": summary,
        "cloud_now_pct": now_cloud,
        "best_window_start": best[0] if best else None,
        "best_window_end": best[1] if best else None,
    }


def fetch_point_weather(lat: float, lng: float) -> dict[str, Any]:
    """Current conditions, 48h hourly cloud cover, and 7-day daily outlook."""
    cache_key = f"{round(lat, 1)}_{round(lng, 1)}"
    cached = _weather_cache.get(cache_key)
    if cached is not None:
        return cached

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lng}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,cloud_cover,"
        "wind_speed_10m,wind_direction_10m,weather_code,visibility"
        "&hourly=cloud_cover,precipitation_probability,precipitation,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,cloud_cover_mean,wind_speed_10m_max"
        "&forecast_days=7&timezone=UTC"
    )

    try:
        res = fetch_with_curl(url, timeout=12)
        if res.status_code != 200:
            logger.warning("Open-Meteo HTTP %s for %.2f,%.2f", res.status_code, lat, lng)
            return {"error": f"Open-Meteo HTTP {res.status_code}"}
        raw = res.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Open-Meteo fetch failed for %.2f,%.2f: %s", lat, lng, exc)
        return {"error": "Weather forecast unavailable"}

    current_raw = raw.get("current") or {}
    hourly_raw = raw.get("hourly") or {}
    daily_raw = raw.get("daily") or {}

    hourly_times = hourly_raw.get("time") or []
    hourly: list[dict[str, Any]] = []
    for idx, time_str in enumerate(hourly_times[:48]):
        code = _safe_index(hourly_raw.get("weather_code"), idx)
        hourly.append(
            {
                "time": time_str,
                "cloud_cover_pct": _safe_index(hourly_raw.get("cloud_cover"), idx),
                "precip_prob_pct": _safe_index(hourly_raw.get("precipitation_probability"), idx),
                "precip_mm": _safe_index(hourly_raw.get("precipitation"), idx),
                "weather_code": code,
                "conditions": weather_code_label(code),
            }
        )

    daily_times = daily_raw.get("time") or []
    daily: list[dict[str, Any]] = []
    for idx, date_str in enumerate(daily_times[:7]):
        code = _safe_index(daily_raw.get("weather_code"), idx)
        daily.append(
            {
                "date": date_str,
                "temp_max_c": _safe_index(daily_raw.get("temperature_2m_max"), idx),
                "temp_min_c": _safe_index(daily_raw.get("temperature_2m_min"), idx),
                "precip_mm": _safe_index(daily_raw.get("precipitation_sum"), idx),
                "cloud_mean_pct": _safe_index(daily_raw.get("cloud_cover_mean"), idx),
                "wind_max_kmh": _safe_index(daily_raw.get("wind_speed_10m_max"), idx),
                "weather_code": code,
                "conditions": weather_code_label(code),
            }
        )

    code_now = current_raw.get("weather_code")
    payload: dict[str, Any] = {
        "source": "Open-Meteo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "timezone": raw.get("timezone") or "UTC",
        "current": {
            "time": current_raw.get("time"),
            "temperature_c": current_raw.get("temperature_2m"),
            "humidity_pct": current_raw.get("relative_humidity_2m"),
            "precipitation_mm": current_raw.get("precipitation"),
            "cloud_cover_pct": current_raw.get("cloud_cover"),
            "wind_speed_kmh": current_raw.get("wind_speed_10m"),
            "wind_direction_deg": current_raw.get("wind_direction_10m"),
            "visibility_m": current_raw.get("visibility"),
            "weather_code": code_now,
            "conditions": weather_code_label(code_now),
        },
        "hourly_next_48h": hourly,
        "daily_7d": daily,
        "optical_window": _optical_window(hourly),
    }

    _weather_cache[cache_key] = payload
    return payload


def _safe_index(values: list[Any] | None, idx: int) -> Any:
    if not values or idx >= len(values):
        return None
    return values[idx]