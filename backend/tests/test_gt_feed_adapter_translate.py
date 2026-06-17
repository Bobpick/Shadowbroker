"""GT feed adapter uses Telegram English translations for costly-signal matching."""

from __future__ import annotations

from analytics.feed_adapter import normalize_feed_item


def test_telegram_prefers_translated_text_for_gt() -> None:
    post = {
        "title": "Київ 1х БпЛА",
        "description": "Обстріл біля Харкова",
        "title_translated": "Kyiv 1x UAV",
        "description_translated": "Shelling near Kharkiv with troop movement reported",
        "source": "t.me/osintdefender",
        "coords": [49.99, 36.23],
    }
    item = normalize_feed_item(post, source_type="telegram_osint")
    assert "troop movement" in item["text"].lower()
    assert item["domain"] == "conflict"


def test_hashtag_region_maps_ukraine_dossier_key() -> None:
    post = {
        "title": "Update",
        "description_translated": "#Ukraine #USA aircraft spotted on runway",
        "source": "t.me/osintdefender",
    }
    item = normalize_feed_item(post, source_type="telegram_osint")
    assert item["region"] == "ukraine"


def test_reddit_prefers_translated_text_for_gt() -> None:
    post = {
        "title": "Удары по инфраструктуре",
        "description": "Обстрел продолжается в приграничных районах",
        "title_translated": "Strikes on infrastructure",
        "description_translated": "Shelling continues in border areas with troop buildup reported",
        "subreddit": "Russia",
        "narrative_profile": "adversarial",
        "source": "reddit.com/r/Russia",
        "coords": [50.45, 30.52],
    }
    item = normalize_feed_item(post, source_type="reddit_osint")
    assert "troop buildup" in item["text"].lower()
    assert item["domain"] == "conflict"
    assert "subreddit:Russia" in item["entities"]
    assert "narrative:adversarial" in item["entities"]