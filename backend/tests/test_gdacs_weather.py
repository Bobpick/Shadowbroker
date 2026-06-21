"""Tests for GDACS global weather hazard fetcher."""

from unittest.mock import MagicMock, patch

from services.gdacs_weather import _gdacs_severity, fetch_global_weather_hazards


def test_gdacs_severity_mapping():
    assert _gdacs_severity("red") == "Extreme"
    assert _gdacs_severity("orange") == "Severe"
    assert _gdacs_severity("green") == "Moderate"
    assert _gdacs_severity("unknown") == "Unknown"


def test_fetch_global_weather_hazards_parses_events():
    mock_list = MagicMock()
    mock_list.status_code = 200
    mock_list.json.return_value = {
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [11.0, 20.0], [11.0, 21.0], [10.0, 20.0]]],
                },
                "properties": {
                    "eventtype": "TC",
                    "eventid": 42,
                    "episodeid": 7,
                    "name": "Cyclone Test",
                    "alertlevel": "red",
                    "iscurrent": "true",
                    "country": "Exampleland",
                    "description": "Strong cyclone approaching coast",
                    "htmldescription": "Cyclone Test — red alert",
                    "todate": "2099-12-31T00:00:00Z",
                    "url": {"report": "https://www.gdacs.org/report/example"},
                },
            }
        ]
    }

    with patch("services.gdacs_weather.fetch_with_curl", return_value=mock_list):
        hazards = fetch_global_weather_hazards(geometry_limit=0)

    assert len(hazards) == 1
    row = hazards[0]
    assert row["id"] == "gdacs-TC-42-7"
    assert row["event"] == "Cyclone Test"
    assert row["severity"] == "Extreme"
    assert row["source"] == "GDACS"
    assert row["country"] == "Exampleland"
    assert row["report_url"] == "https://www.gdacs.org/report/example"
    assert row["geometry"]["type"] == "Polygon"


def test_fetch_global_weather_hazards_skips_stale_events():
    mock_list = MagicMock()
    mock_list.status_code = 200
    mock_list.json.return_value = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {
                    "eventtype": "FL",
                    "eventid": 1,
                    "episodeid": 1,
                    "name": "Old Flood",
                    "alertlevel": "green",
                    "iscurrent": "false",
                    "todate": "2000-01-01T00:00:00Z",
                },
            }
        ]
    }

    with patch("services.gdacs_weather.fetch_with_curl", return_value=mock_list):
        hazards = fetch_global_weather_hazards()

    assert hazards == []