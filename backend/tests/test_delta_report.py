"""Delta report change detection + executive briefing render."""

from __future__ import annotations

from analytics.delta_report import (
    alert_level,
    compute_deltas,
    render_markdown,
    risk_word,
    sparkline,
    threat_meter_line,
)


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
    assert "flashpoints_ranked" in delta


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
    assert delta["has_meaningful_change"] is False or len(delta["top_region_shifts"]) == 0


def test_alert_levels_and_risk_words():
    assert alert_level(80, 90, "stable") == "GREEN"
    assert alert_level(40, 50, "watch") == "ORANGE"
    assert alert_level(25, 20, "unstable") == "BLACK"  # det < 30 + unstable
    assert alert_level(32, 20, "unstable") == "RED"
    assert risk_word(70) == "HIGH"
    assert "█" in sparkline([10, 20, 40, 80, 50])


def test_render_markdown_decision_support_structure():
    delta = {
        "threshold": 0.08,
        "first_run": False,
        "previous_generated_at": "2026-07-20T12:00:00+00:00",
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
        "flashpoints_ranked": [
            {
                "id": "taiwan_strait",
                "label": "Taiwan Strait",
                "nash_score": 40,
                "nash_band": "watch",
                "deterrence": {"score": 33, "band": "fragile", "max_gt_risk": 0.4},
                "prev_deterrence": 55,
                "prev_nash": 70,
                "det_delta": -22,
                "nash_delta": -30,
                "alert_level": "RED",
                "alert_label": "Critical",
                "confidence": "Medium",
                "drivers": ["Deterrence posture weakened", "Nash stability declined"],
                "keyword_hits": 3,
                "gt_scores": {"china": 0.4},
                "det_history": [55, 48, 40, 33],
                "sparkline": "▇▅▃▂",
                "theater": "Indo-Pacific",
                "arrow": {"label": "toward_eq"},
            },
            {
                "id": "strait_of_hormuz",
                "label": "Strait of Hormuz",
                "nash_score": 100,
                "nash_band": "stable",
                "deterrence": {"score": 72, "band": "strong", "max_gt_risk": 0.1},
                "prev_deterrence": 60,
                "prev_nash": 100,
                "det_delta": 12,
                "nash_delta": 0,
                "alert_level": "GREEN",
                "alert_label": "Stable",
                "confidence": "High",
                "drivers": ["Deterrence posture improved"],
                "keyword_hits": 0,
                "gt_scores": {},
                "det_history": [60, 65, 70, 72],
                "sparkline": "▄▅▆▇",
                "theater": "Middle East",
                "arrow": {"label": "equilibrium"},
            },
        ],
        "us_cities": [
            {
                "label": "New York City",
                "protest_potential": 0.2,
                "unrest": 0.15,
                "protest_mentions": 2,
            }
        ],
        "strategic": {"flashpoints": []},
    }
    md = render_markdown(delta, generated_at="2026-07-21T00:00:00+00:00")
    for needle in (
        "GLOBAL STRATEGIC POSTURE",
        "EXECUTIVE ASSESSMENT",
        "WHAT CHANGED SINCE PREVIOUS REPORT",
        "TOP CHANGES",
        "STATISTICS",
        "FLASHPOINT WATCH",
        "Priority 1",
        "Taiwan Strait",
        "Primary Drivers",
        "REGIONAL STABILITY HEAT",
        "DOMESTIC STABILITY",
        "WATCH CONDITIONS",
        "ANALYST NOTE",
        "24-HOUR OUTLOOK",
        "METHODOLOGY",
        "Global Strategic Risk",
    ):
        assert needle in md, f"missing section: {needle}"
    assert "▼" in md or "▲" in md
    meter = "\n".join(threat_meter_line(63))
    assert "63" in meter or "63" in md
