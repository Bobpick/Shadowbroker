"""Tests for lightweight point weather API."""

from unittest.mock import patch


def test_weather_point_api_returns_payload(client):
    mock_payload = {
        "source": "Open-Meteo",
        "current": {"conditions": "Overcast", "cloud_cover_pct": 82},
        "optical_window": {"status": "fair", "summary": "Cloudy now"},
    }
    with patch("services.open_meteo.fetch_point_weather", return_value=mock_payload):
        response = client.get("/api/weather/point?lat=44.12&lng=-122.38")
    assert response.status_code == 200
    body = response.json()
    assert body["current"]["conditions"] == "Overcast"
    assert body["optical_window"]["status"] == "fair"


def test_weather_point_api_rejects_invalid_lat(client):
    response = client.get("/api/weather/point?lat=999&lng=0")
    assert response.status_code == 422