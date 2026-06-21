"""GT region geographic normalization tests."""

from __future__ import annotations

from analytics.feed_adapter import normalize_feed_item
from analytics.gt_alerts import parse_heatmap_alerts
from analytics.region_geo import (
    diversify_alerts_by_distance,
    resolve_region_from_coords,
    theater_from_coords,
)


def test_kyiv_coords_resolve_to_ukraine_theater() -> None:
    assert theater_from_coords(50.45, 30.52) == "ukraine"
    assert resolve_region_from_coords(50.45, 30.52) == "ukraine"


def test_far_ocean_coords_use_coarse_grid() -> None:
    assert resolve_region_from_coords(12.345, -45.678) == "12.3,-45.7"


def test_normalize_feed_item_assigns_theater_centroid_when_missing_coords() -> None:
    item = normalize_feed_item(
        {"title": "Update", "description": "#Ukraine troop movement near border"},
        source_type="telegram_osint",
    )
    assert item["region"] == "ukraine"
    assert item["coords"] == [48.38, 31.17]


def test_diversify_alerts_spreads_nearby_regions() -> None:
    heatmap = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"region": "ukraine", "risk": 0.8, "conflict": 0.7, "updates": 3},
                "geometry": {"type": "Point", "coordinates": [31.0, 48.0]},
            },
            {
                "type": "Feature",
                "properties": {"region": "48.50,31.20", "risk": 0.79, "conflict": 0.69, "updates": 2},
                "geometry": {"type": "Point", "coordinates": [31.2, 48.5]},
            },
            {
                "type": "Feature",
                "properties": {"region": "israel", "risk": 0.7, "conflict": 0.6, "updates": 2},
                "geometry": {"type": "Point", "coordinates": [35.2, 31.8]},
            },
        ],
    }
    alerts, plotted = parse_heatmap_alerts(heatmap, limit=2)
    assert plotted == 3
    assert len(alerts) == 2
    regions = {row["region"] for row in alerts}
    assert "ukraine" in regions
    assert "israel" in regions


def test_baseline_theaters_excluded_from_top_alerts() -> None:
    heatmap = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "region": "ukraine",
                    "risk": 0.68,
                    "conflict": 0.83,
                    "updates": 12,
                },
                "geometry": {"type": "Point", "coordinates": [31.0, 48.0]},
            },
            {
                "type": "Feature",
                "properties": {
                    "region": "iran",
                    "risk": 0.15,
                    "conflict": 0.15,
                    "updates": 1,
                },
                "geometry": {"type": "Point", "coordinates": [53.69, 32.43]},
            },
            {
                "type": "Feature",
                "properties": {
                    "region": "russia",
                    "risk": 0.15,
                    "conflict": 0.15,
                    "updates": 1,
                },
                "geometry": {"type": "Point", "coordinates": [37.62, 55.75]},
            },
        ],
    }
    alerts, plotted = parse_heatmap_alerts(heatmap, limit=8, base_prior=0.15)
    assert plotted == 3
    assert len(alerts) == 1
    assert alerts[0]["region"] == "ukraine"


def test_diversify_alerts_marks_nearby_count() -> None:
    rows = [
        {"region": "a", "lat": 48.0, "lng": 31.0, "score": 0.9},
        {"region": "b", "lat": 48.5, "lng": 31.5, "score": 0.8},
        {"region": "c", "lat": 31.8, "lng": 35.2, "score": 0.7},
    ]
    picked = diversify_alerts_by_distance(rows, limit=2, min_separation_km=160.0)
    assert len(picked) == 2
    assert picked[0].get("nearby_count", 1) >= 2