"""Tests for NWS weather alert zone-geometry resolution."""

from unittest.mock import MagicMock, patch

from services.fetchers import earth_observation as eo


def test_nws_zone_urls_from_affected_zones_and_ugc():
    props = {
        "affectedZones": [
            "https://api.weather.gov/zones/forecast/ORZ023",
            "https://api.weather.gov/zones/forecast/orz024",
            "https://api.weather.gov/zones/forecast/ORZ023",  # dup
        ],
        "geocode": {"UGC": ["ORZ099", "bad"]},
    }
    urls = eo._nws_zone_urls_from_alert(props)
    assert urls == [
        "https://api.weather.gov/zones/forecast/ORZ023",
        "https://api.weather.gov/zones/forecast/ORZ024",
    ]

    props_ugc_only = {"affectedZones": [], "geocode": {"UGC": ["orc051", "ORZ110"]}}
    assert eo._nws_zone_urls_from_alert(props_ugc_only) == [
        "https://api.weather.gov/zones/county/ORC051",
        "https://api.weather.gov/zones/forecast/ORZ110",
    ]


def test_zone_prefetch_order_is_round_robin_across_alerts():
    """Multi-zone alerts must not starve later alerts in the fetch budget."""
    features = [
        {
            "geometry": None,
            "properties": {
                "affectedZones": [
                    "https://api.weather.gov/zones/forecast/ORZ001",
                    "https://api.weather.gov/zones/forecast/ORZ002",
                    "https://api.weather.gov/zones/forecast/ORZ003",
                ]
            },
        },
        {
            "geometry": None,
            "properties": {
                "affectedZones": ["https://api.weather.gov/zones/forecast/WAZ001"]
            },
        },
        {
            "geometry": None,
            "properties": {
                "affectedZones": [
                    "https://api.weather.gov/zones/forecast/CAZ001",
                    "https://api.weather.gov/zones/forecast/CAZ002",
                ]
            },
        },
        # Inline geometry — should not contribute zones
        {
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {
                "affectedZones": ["https://api.weather.gov/zones/forecast/TXZ001"]
            },
        },
    ]
    need = eo._nws_zone_urls_round_robin(features)
    assert need[:3] == [
        "https://api.weather.gov/zones/forecast/ORZ001",
        "https://api.weather.gov/zones/forecast/WAZ001",
        "https://api.weather.gov/zones/forecast/CAZ001",
    ]
    assert "TXZ001" not in "".join(need)
    assert need == [
        "https://api.weather.gov/zones/forecast/ORZ001",
        "https://api.weather.gov/zones/forecast/WAZ001",
        "https://api.weather.gov/zones/forecast/CAZ001",
        "https://api.weather.gov/zones/forecast/ORZ002",
        "https://api.weather.gov/zones/forecast/CAZ002",
        "https://api.weather.gov/zones/forecast/ORZ003",
    ]


def test_merge_zone_geometries_polygon_and_multi():
    poly_a = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    }
    poly_b = {
        "type": "Polygon",
        "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]],
    }
    assert eo._merge_zone_geometries([poly_a])["type"] == "Polygon"
    multi = eo._merge_zone_geometries([poly_a, poly_b])
    assert multi["type"] == "MultiPolygon"
    assert len(multi["coordinates"]) == 2
    assert eo._merge_zone_geometries([]) is None


def test_fetch_weather_alerts_resolves_zone_only_heat_advisory():
    """Heat advisories often have geometry=null; expand via zone polygons."""
    zone_url = "https://api.weather.gov/zones/forecast/ORZ023"
    alert_resp = MagicMock()
    alert_resp.status_code = 200
    alert_resp.json.return_value = {
        "features": [
            {
                "geometry": None,
                "properties": {
                    "id": "https://api.weather.gov/alerts/urn:oid:heat-or",
                    "event": "Heat Advisory",
                    "severity": "Moderate",
                    "certainty": "Likely",
                    "urgency": "Expected",
                    "headline": "Heat Advisory for Central Douglas County",
                    "description": "Hot temperatures expected.",
                    "expires": "2099-08-05T06:00:00+00:00",
                    "affectedZones": [zone_url],
                    "geocode": {"UGC": ["ORZ023"]},
                },
            },
            {
                "geometry": None,
                "properties": {
                    "id": "no-zones",
                    "event": "Special Weather Statement",
                    "severity": "Minor",
                    "affectedZones": [],
                },
            },
        ]
    }

    zone_resp = MagicMock()
    zone_resp.status_code = 200
    zone_resp.json.return_value = {
        "type": "Feature",
        "properties": {"id": "ORZ023"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-123.5, 43.1], [-123.0, 43.1], [-123.0, 43.5], [-123.5, 43.1]]
            ],
        },
    }

    def _fake_curl(url, timeout=15, headers=None):
        if "alerts/active" in url:
            return alert_resp
        if url == zone_url or url.rstrip("/").endswith("/ORZ023"):
            return zone_resp
        raise AssertionError(f"unexpected url {url}")

    eo._NWS_ZONE_GEOM_CACHE.clear()
    eo._NWS_ZONE_CACHE_LOADED = True

    with (
        patch("services.fetchers.earth_observation.fetch_with_curl", side_effect=_fake_curl),
        patch("services.fetchers.earth_observation._persist_nws_zone_geom_cache"),
        patch("services.fetchers._store.is_any_active", return_value=True),
        patch("services.fetchers.earth_observation._mark_fresh"),
        patch("services.network_utils.outbound_user_agent", return_value="test-agent"),
    ):
        with eo._data_lock:
            eo.latest_data["weather_alerts"] = []
        eo.fetch_weather_alerts()
        alerts = eo.latest_data.get("weather_alerts") or []

    assert len(alerts) == 1
    assert alerts[0]["event"] == "Heat Advisory"
    assert alerts[0]["geometry"]["type"] == "Polygon"
    assert alerts[0]["severity"] == "Moderate"
    assert zone_url in eo._NWS_ZONE_GEOM_CACHE
