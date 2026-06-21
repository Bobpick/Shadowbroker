"""Wastewater trend analysis and national rollup tests."""

from datetime import datetime, timedelta, timezone

from services.fetchers.wastewater_trends import (
    build_pathogen_rollups,
    build_surveillance_summary,
    compute_pathogen_trend,
    parse_plant_series,
)

TARGETS = {
    "Rota": "Rotavirus",
    "N Gene": "COVID-19",
}


def test_compute_pathogen_trend_detects_escalation():
    history = [
        {"activity_rank": 4, "alert": False, "normalized": 0.0001},
        {"activity_rank": 4, "alert": False, "normalized": 0.0002},
        {"activity_rank": 6, "alert": True, "normalized": 0.0003},
    ]
    assert compute_pathogen_trend(history) == "rising"


def test_parse_plant_series_extracts_trend_and_history():
    today = datetime.now(timezone.utc).date()
    early = (today - timedelta(days=14)).isoformat()
    recent = (today - timedelta(days=2)).isoformat()
    samples = [
        {
            "collection_date": early,
            "targets": {
                "Rota": {
                    "gc_g_dry_weight": 1000,
                    "gc_g_dry_weight_pmmov": 0.0001,
                    "activity_category": "medium",
                }
            },
        },
        {
            "collection_date": recent,
            "targets": {
                "Rota": {
                    "gc_g_dry_weight": 5000,
                    "gc_g_dry_weight_pmmov": 0.0003,
                    "activity_category": "high",
                }
            },
        },
    ]

    parsed = parse_plant_series(
        samples,
        TARGETS,
        window_days=21,
        max_age_days=30,
    )

    assert parsed is not None
    rota = next(item for item in parsed["pathogens"] if item["name"] == "Rotavirus")
    assert rota["trend"] == "rising"
    assert rota["alert"] is True
    assert len(rota["history"]) == 2


def test_build_surveillance_summary_aggregates_states_and_rates():
    plants = [
        {
            "state": "Kansas",
            "pathogens": [
                {"name": "Rotavirus", "target_key": "Rota", "alert": True, "trend": "rising"},
                {"name": "COVID-19", "target_key": "N Gene", "alert": False, "trend": "stable"},
            ],
        },
        {
            "state": "Michigan",
            "pathogens": [
                {"name": "Rotavirus", "target_key": "Rota", "alert": True, "trend": "rising"},
            ],
        },
    ]
    rollups = build_pathogen_rollups(plants)
    summary = build_surveillance_summary(
        plants,
        baseline={
            "date": "2026-06-09",
            "pathogens": {
                "Rotavirus": {"states_rising_count": 1, "states_alert_count": 1},
            },
        },
    )

    rota = next(item for item in summary["rising_pathogens"] if item["name"] == "Rotavirus")
    assert rota["states_rising"] == 2
    assert rota["states_alert"] == 2
    assert rota["states_rising_delta"] == 1
    assert rota["rising_rate_pct"] == 100.0
    assert rota["rising_rate_display"] == "+100.0%"
    assert summary["pathogens_rising"] >= 1


def test_build_surveillance_summary_new_signal_without_baseline():
    plants = [
        {
            "state": "Kansas",
            "pathogens": [
                {"name": "Rotavirus", "target_key": "Rota", "alert": True, "trend": "rising"},
            ],
        },
    ]
    summary = build_surveillance_summary(plants, baseline=None)
    rota = summary["rising_pathogens"][0]
    assert rota["rising_rate_pct"] is None
    assert rota["rising_rate_display"] == "+1 states (new)"