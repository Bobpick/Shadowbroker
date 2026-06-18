"""Tests for Open-Meteo point weather integration."""

from unittest.mock import MagicMock, patch

from services.open_meteo import fetch_point_weather, weather_code_label


def test_weather_code_label():
    assert weather_code_label(0) == "Clear"
    assert weather_code_label(3) == "Overcast"
    assert weather_code_label(99) == "Thunderstorm with heavy hail"


def test_fetch_point_weather_parses_response():
    payload = {
        "timezone": "Europe/Kyiv",
        "current": {
            "time": "2026-06-18T12:00",
            "temperature_2m": 22.5,
            "relative_humidity_2m": 61,
            "precipitation": 0.0,
            "cloud_cover": 82,
            "wind_speed_10m": 14.0,
            "wind_direction_10m": 180,
            "weather_code": 3,
            "visibility": 12000,
        },
        "hourly": {
            "time": ["2026-06-18T12:00", "2026-06-18T13:00", "2026-06-18T14:00"],
            "cloud_cover": [82, 45, 20],
            "precipitation_probability": [10, 5, 0],
            "precipitation": [0.0, 0.0, 0.0],
            "weather_code": [3, 2, 1],
        },
        "daily": {
            "time": ["2026-06-18"],
            "weather_code": [3],
            "temperature_2m_max": [24.0],
            "temperature_2m_min": [16.0],
            "precipitation_sum": [1.2],
            "cloud_cover_mean": [55.0],
            "wind_speed_10m_max": [18.0],
        },
    }
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = payload

    with patch("services.open_meteo.fetch_with_curl", return_value=mock_res):
        result = fetch_point_weather(50.45, 30.52)

    assert result["source"] == "Open-Meteo"
    assert result["current"]["cloud_cover_pct"] == 82
    assert result["current"]["conditions"] == "Overcast"
    assert len(result["hourly_next_48h"]) == 3
    assert result["daily_7d"][0]["temp_max_c"] == 24.0
    assert result["optical_window"]["status"] in {"fair", "poor", "good"}