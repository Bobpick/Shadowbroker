"""Tests for GT weather noise modifier and collection planner context."""

from unittest.mock import patch

from analytics.gt_weather_modifier import (
    assess_weather_context,
    clear_weather_cache,
    enrich_heatmap_with_weather,
    weather_evidence_multiplier,
)


def _storm_weather() -> dict:
    return {
        "source": "Open-Meteo",
        "current": {
            "conditions": "Thunderstorm",
            "weather_code": 95,
            "precipitation_mm": 4.2,
            "wind_speed_kmh": 48,
            "cloud_cover_pct": 98,
        },
        "hourly_next_48h": [
            {"time": "2026-06-18T12:00", "cloud_cover_pct": 95},
            {"time": "2026-06-18T13:00", "cloud_cover_pct": 92},
        ],
        "optical_window": {
            "status": "poor",
            "summary": "Heavy cloud cover (98%) — optical sat likely blind for 48h",
        },
    }


def test_assess_weather_context_storm_noise():
    ctx = assess_weather_context(_storm_weather(), region="ukraine")
    assert ctx["weather_noise"] >= 0.45
    assert ctx["collection_recommendation"] == "sar_recommended"
    assert "SAR RECOMMENDED" in ctx["collection_badge"]
    assert ctx["gt_note"]


def test_weather_evidence_multiplier_damps_storms():
    ctx = assess_weather_context(_storm_weather())
    assert weather_evidence_multiplier(ctx) < 0.85


def test_enrich_heatmap_with_weather_attaches_props():
    clear_weather_cache()
    heatmap = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"region": "ukraine", "risk": 0.4, "unrest": 0.35, "conflict": 0.3},
                "geometry": {"type": "Point", "coordinates": [31.17, 48.38]},
            }
        ],
    }
    mock_weather = _storm_weather()

    with patch(
        "analytics.gt_weather_modifier.fetch_point_weather",
        return_value=mock_weather,
    ):
        enriched = enrich_heatmap_with_weather(heatmap)

    props = enriched["features"][0]["properties"]
    assert props["weather_noise"] >= 0.45
    assert props["collection_badge"]
    assert props["unrest_weather_adj"] >= props["unrest"]
    assert enriched.get("weather_enriched") is True