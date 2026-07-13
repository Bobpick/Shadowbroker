"""US metro protest watch tests."""

from __future__ import annotations

from analytics.us_cities import (
    build_us_city_watch,
    resolve_us_city,
    us_city_from_coords,
    us_city_label,
)


def test_us_city_from_coords_dc():
    assert us_city_from_coords(38.907, -77.036) == "washington_dc"


def test_us_city_from_coords_portland():
    assert us_city_from_coords(45.52, -122.67) == "portland"


def test_resolve_us_city_from_subreddit():
    assert resolve_us_city(source="r/PortlandDSA", text="DSA chapter update") == "portland"
    assert resolve_us_city(source="r/EyesOnICEBaltimore", text="ICE watch tonight") == "baltimore"


def test_resolve_us_city_from_dsa_telegram_chapters():
    assert resolve_us_city(source="t.me/PhillyDSA", text="Chapter meeting tonight") == "philadelphia"
    assert resolve_us_city(source="@BostonDSA", text="Direct action briefing") == "boston"
    assert resolve_us_city(source="SeattleDSA", text="Rally scheduled") == "seattle"
    assert resolve_us_city(source="BayAreaDSA", text="SF march this weekend") == "san_francisco"
    assert resolve_us_city(source="sfdsa", text="Bay Area mobilization") == "san_francisco"
    assert resolve_us_city(source="ATLDsa", text="Atlanta protest watch") == "atlanta"
    assert resolve_us_city(source="HoustonDSA", text="Houston rally at city hall") == "houston"


def test_resolve_us_city_from_text():
    assert resolve_us_city(text="Mass rally scheduled in Chicago this weekend") == "chicago"


def test_us_city_label():
    assert us_city_label("new_york") == "New York City"
    assert us_city_label("houston") == "Houston"
    assert us_city_label("phoenix") == "Phoenix"


def test_resolve_us_city_houston_detroit_phoenix():
    assert resolve_us_city(text="Rally planned in Houston downtown") == "houston"
    assert resolve_us_city(text="Detroit ICE protest mobilization Saturday") == "detroit"
    assert us_city_from_coords(33.45, -112.07) == "phoenix"


def test_build_us_city_watch_ranks_protest_feeds():
    now_iso = "2026-07-10T12:00:00+00:00"
    report = build_us_city_watch(
        gt_risk={
            "heatmap": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-77.036, 38.907]},
                        "properties": {
                            "region": "washington_dc",
                            "risk": 0.22,
                            "unrest": 0.31,
                            "conflict": 0.05,
                        },
                    }
                ],
            }
        },
        reddit_osint={
            "posts": [
                {
                    "title": "Protest scheduled downtown",
                    "description": "Direct action briefing in Portland — meet at city hall",
                    "published": now_iso,
                    "source": "r/PortlandDSA",
                    "subreddit": "PortlandDSA",
                    "narrative_profile": "protest",
                    "coords": [45.515, -122.679],
                    "link": "https://reddit.com/r/PortlandDSA/1",
                },
                {
                    "title": "ICE rally mobilization",
                    "description": "Mass rally at Baltimore city hall tomorrow",
                    "published": now_iso,
                    "source": "r/EyesOnICEBaltimore",
                    "subreddit": "EyesOnICEBaltimore",
                    "narrative_profile": "protest",
                    "link": "https://reddit.com/r/EyesOnICEBaltimore/2",
                },
            ]
        },
        telegram_osint={"posts": []},
        lookback_days=7,
        limit=8,
    )

    assert report["enabled"] is True
    cities = report["cities"]
    assert cities
    keys = [row["city"] for row in cities]
    assert "portland" in keys
    assert "baltimore" in keys
    portland = next(row for row in cities if row["city"] == "portland")
    assert portland["protest_mentions"] >= 1
    assert portland["mobilization_hits"] >= 1
    assert portland["protest_potential"] > 0.1