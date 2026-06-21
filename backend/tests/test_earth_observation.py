"""Earth-observation fetcher helpers."""

from services.fetchers.earth_observation import _parse_usgs_earthquake_feature


def test_parse_usgs_earthquake_feature_extracts_time_and_depth():
    feature = {
        "id": "us7000abc",
        "geometry": {"coordinates": [-125.136, 40.374, 12.5]},
        "properties": {
            "mag": 3.2,
            "place": "72 km W of Petrolia, CA",
            "time": 1_750_000_000_000,
            "updated": 1_750_000_500_000,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abc",
        },
    }

    parsed = _parse_usgs_earthquake_feature(feature)

    assert parsed is not None
    assert parsed["mag"] == 3.2
    assert parsed["depth_km"] == 12.5
    assert parsed["place"] == "72 km W of Petrolia, CA"
    assert parsed["time"] == "2025-06-15T15:06:40+00:00"
    assert parsed["url"].endswith("us7000abc")


def test_parse_usgs_earthquake_feature_rejects_invalid_geometry():
    assert _parse_usgs_earthquake_feature({"geometry": {"coordinates": [1.0, 2.0]}}) is None