"""Reddit OSINT parser and retention tests."""

from datetime import datetime, timezone

from services.fetchers.reddit_osint import (
    parse_reddit_listing,
    prune_reddit_posts,
    reddit_max_age_days,
)


def test_parse_reddit_listing_geoparses_and_tags_adversarial():
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Missile strike reported near Kyiv amid escalation",
                        "selftext": "Multiple sources reporting increased activity.",
                        "permalink": "/r/Russia/comments/abc/test/",
                        "created_utc": datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc).timestamp(),
                        "subreddit": "Russia",
                        "author": "example_user",
                        "score": 42,
                    }
                }
            ]
        }
    }

    posts = parse_reddit_listing(payload, "Russia")
    assert len(posts) == 1
    post = posts[0]
    assert post["subreddit"] == "Russia"
    assert post["narrative_profile"] == "adversarial"
    assert post["coords"] is not None
    assert post["risk_score"] >= 3
    assert post["link"].startswith("https://www.reddit.com/")


def test_prune_reddit_posts_drops_old_entries():
    posts = [
        {"published": "2020-01-01T00:00:00+00:00", "link": "https://reddit.com/a"},
        {"published": datetime.now(timezone.utc).isoformat(), "link": "https://reddit.com/b"},
    ]
    pruned = prune_reddit_posts(posts, max_age_days=7)
    assert len(pruned) == 1
    assert pruned[0]["link"].endswith("/b")


def test_reddit_max_age_days_default():
    assert reddit_max_age_days() >= 1