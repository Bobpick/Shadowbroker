"""Tests for pure Nash solver + strategic analysis builders."""

from __future__ import annotations

from analytics.nash_deterrence import (
    analyze_flashpoint,
    build_strategic_analysis,
    nash_stability_score,
    pure_nash_equilibria,
)


def test_pure_nash_prisoners_dilemma_like():
    # Classic PD: only (D,D) is pure NE
    payoffs = [
        [(3.0, 3.0), (0.0, 5.0)],
        [(5.0, 0.0), (1.0, 1.0)],
    ]
    eqs = pure_nash_equilibria(payoffs)
    assert eqs == [(1, 1)]


def test_pure_nash_coordination_two_eq():
    payoffs = [
        [(2.0, 2.0), (0.0, 0.0)],
        [(0.0, 0.0), (1.0, 1.0)],
    ]
    eqs = pure_nash_equilibria(payoffs)
    assert (0, 0) in eqs
    assert (1, 1) in eqs


def test_stability_higher_on_equilibrium():
    payoffs = [
        [(3.0, 3.0), (0.0, 5.0)],
        [(5.0, 0.0), (1.0, 1.0)],
    ]
    on_eq = nash_stability_score(payoffs, 1, 1)
    off_eq = nash_stability_score(payoffs, 0, 0)
    assert on_eq > off_eq
    assert on_eq >= 70


def test_analyze_flashpoint_shape():
    fp = {
        "id": "test_fp",
        "label": "Test",
        "lat": 0.0,
        "lng": 0.0,
        "row_actor": "A",
        "col_actor": "B",
        "row_strategies": ["C", "D"],
        "col_strategies": ["C", "D"],
        "payoffs": [
            [[3, 3], [1, 4]],
            [[4, 1], [2, 2]],
        ],
        "gt_regions": ["ukraine"],
        "keywords": ["artillery"],
        "locked_strategies": True,
        "current_row": 0,
        "current_col": 0,
    }
    out = analyze_flashpoint(
        fp,
        gt_risk={
            "heatmap": {
                "features": [
                    {
                        "properties": {
                            "region": "ukraine",
                            "risk": 0.5,
                            "conflict": 0.55,
                            "unrest": 0.2,
                        }
                    }
                ]
            }
        },
        telegram={"posts": [{"title": "Artillery barrage overnight", "description": ""}]},
        reddit={"posts": []},
    )
    assert out["id"] == "test_fp"
    assert 0 <= out["nash_score"] <= 100
    assert out["deterrence"]["score"] >= 0
    assert "equilibria" in out
    assert out["keyword_hits"] >= 1


def test_build_strategic_analysis_returns_payload():
    report = build_strategic_analysis(gt_risk={"heatmap": {"features": []}})
    assert "enabled" in report
    assert "flashpoints" in report
    if report["enabled"]:
        assert isinstance(report["flashpoints"], list)
