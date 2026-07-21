"""Delta report change detection + markdown render."""

from __future__ import annotations

from analytics.delta_report import compute_deltas, render_markdown


def test_compute_deltas_first_run_is_meaningful():
    gt = {
        "heatmap": {
            "features": [
                {
                    "properties": {
                        "region": "ukraine",
                        "risk": 0.4,
                        "conflict": 0.5,
                        "unrest": 0.2,
                        "risk_delta": 0.0,
                    }
                }
            ]
        },
        "us_cities": {"cities": []},
    }
    delta = compute_deltas(gt, None)
    assert delta["first_run"] is True
    assert delta["has_meaningful_change"] is True


def test_compute_deltas_small_change_skipped_without_prev_threshold():
    prev = {
        "regions": {"ukraine": {"risk": 0.4, "conflict": 0.5, "unrest": 0.2, "risk_delta": 0.0}},
        "flashpoints": [],
    }
    gt = {
        "heatmap": {
            "features": [
                {
                    "properties": {
                        "region": "ukraine",
                        "risk": 0.41,
                        "conflict": 0.5,
                        "unrest": 0.2,
                        "risk_delta": 0.01,
                    }
                }
            ]
        },
        "us_cities": {"cities": []},
    }
    delta = compute_deltas(gt, prev)
    # 0.01 < default 0.08 threshold
    assert delta["has_meaningful_change"] is False or len(delta["top_region_shifts"]) == 0


def test_render_markdown_contains_sections():
    delta = {
        "threshold": 0.08,
        "first_run": True,
        "top_region_shifts": [
            {
                "region": "ukraine",
                "risk": 0.5,
                "prev_risk": 0.3,
                "delta": 0.2,
                "micro_delta": 0.1,
                "ignition": True,
            }
        ],
        "flashpoint_shifts": [],
        "us_cities": [],
        "strategic": {"flashpoints": []},
    }
    md = render_markdown(delta, generated_at="2026-07-17T00:00:00+00:00")
    assert "Executive summary" in md
    assert "ukraine" in md
    assert "Nash / deterrence" in md
