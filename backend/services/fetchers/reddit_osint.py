"""Reddit OSINT — public subreddit listings with keyword geoparsing."""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.fetchers.telegram_osint import _resolve_telegram_coords, _score_risk
from services.network_utils import fetch_with_curl, outbound_user_agent
from services.telegram_translate import apply_reddit_posts_translations

logger = logging.getLogger(__name__)

DEFAULT_REDDIT_MAX_AGE_DAYS = 7

# Geopolitical + adversary-adjacent narrative spaces (public). Override via env.
_DEFAULT_SUBREDDITS: tuple[str, ...] = (
    "geopolitics",
    "worldnews",
    "CredibleDefense",
    "LessCredibleDefence",
    "Russia",
    "china",
    "Iran",
    "Sino",
    "GenZedong",
    "communism",
    "Antiwar",
    "MiddleEastNews",
    "europe",
)

_ADVERSARIAL_SUBREDDITS = frozenset(
    {
        "russia",
        "china",
        "iran",
        "sino",
        "genzedong",
        "communism",
        "antiwar",
    }
)


def reddit_max_age_days() -> int:
    raw = str(os.environ.get("REDDIT_OSINT_MAX_AGE_DAYS", "")).strip()
    if not raw:
        return DEFAULT_REDDIT_MAX_AGE_DAYS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_REDDIT_MAX_AGE_DAYS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_published_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _post_within_retention(
    post: dict[str, Any],
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> bool:
    published = _parse_published_at(post.get("published"))
    if published is None:
        return False
    limit_days = max_age_days if max_age_days is not None else reddit_max_age_days()
    cutoff = (now or _utcnow()) - timedelta(days=limit_days)
    return published >= cutoff


def prune_reddit_posts(
    posts: list[dict[str, Any]],
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        post
        for post in posts
        if _post_within_retention(post, max_age_days=max_age_days, now=now)
    ]


def reddit_osint_enabled() -> bool:
    return str(os.environ.get("REDDIT_OSINT_ENABLED", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def _configured_subreddits() -> list[str]:
    raw = str(os.environ.get("REDDIT_OSINT_SUBREDDITS", "")).strip()
    if raw:
        return [part.strip().lstrip("r/") for part in raw.split(",") if part.strip()]
    return list(_DEFAULT_SUBREDDITS)


def _narrative_profile(subreddit: str) -> str:
    key = str(subreddit or "").strip().lower()
    if key in _ADVERSARIAL_SUBREDDITS:
        return "adversarial"
    if key in {"geopolitics", "worldnews", "credibledefense", "lesscredibledefence", "middleeastnews"}:
        return "geopolitical"
    return "general"


def _post_link(post: dict[str, Any]) -> str:
    return str(post.get("link") or "").strip()


def _merge_reddit_posts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    max_posts: int = 160,
) -> tuple[list[dict[str, Any]], int]:
    known_links = {_post_link(post) for post in existing if _post_link(post)}
    added = 0
    for post in incoming:
        link = _post_link(post)
        if not link or link in known_links:
            continue
        known_links.add(link)
        existing.append(post)
        added += 1
    existing.sort(key=lambda p: str(p.get("published") or ""), reverse=True)
    return prune_reddit_posts(existing[:max_posts]), added


def parse_reddit_listing(payload: dict[str, Any], subreddit: str) -> list[dict[str, Any]]:
    """Parse Reddit /new.json listing into normalized post dicts."""
    children = ((payload.get("data") or {}).get("children") or [])
    posts: list[dict[str, Any]] = []

    for child in children:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        if len(title) < 8:
            continue
        selftext = str(data.get("selftext") or "").strip()
        body = "\n".join(part for part in (title, selftext) if part).strip()
        if len(body) < 12:
            continue

        created = data.get("created_utc")
        if isinstance(created, (int, float)):
            published = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
        else:
            published = _utcnow().isoformat()

        permalink = str(data.get("permalink") or "").strip()
        link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        if not link:
            continue

        sub = str(data.get("subreddit") or subreddit or "").strip()
        text_for_geo = body[:1600]
        coords = _resolve_telegram_coords(text_for_geo)
        post_id = hashlib.sha1(f"{link}|{published}".encode("utf-8")).hexdigest()[:16]

        posts.append(
            {
                "id": post_id,
                "title": title[:200],
                "description": body[:1200],
                "link": link,
                "published": published,
                "source": f"r/{sub}",
                "subreddit": sub,
                "author": str(data.get("author") or ""),
                "reddit_score": int(data.get("score") or 0),
                "risk_score": _score_risk(text_for_geo),
                "narrative_profile": _narrative_profile(sub),
                "coords": [coords[0], coords[1]] if coords else None,
            }
        )

    return prune_reddit_posts(posts)


def fetch_reddit_osint() -> dict[str, Any]:
    if not is_any_active("reddit_osint"):
        return latest_data.get("reddit_osint") or {"posts": [], "total": 0, "timestamp": None}

    if not reddit_osint_enabled():
        with _data_lock:
            latest_data["reddit_osint"] = {"posts": [], "total": 0, "timestamp": None, "disabled": True}
        _mark_fresh("reddit_osint")
        return latest_data["reddit_osint"]

    headers = {
        "User-Agent": (
            f"ShadowbrokerOSINT/1.0 (public narrative monitor; {outbound_user_agent('reddit-osint')})"
        ),
        "Accept": "application/json",
    }

    with _data_lock:
        prior = latest_data.get("reddit_osint") or {}
        existing_posts = prune_reddit_posts(list(prior.get("posts") or []))

    known_links = {_post_link(post) for post in existing_posts if _post_link(post)}
    incoming: list[dict[str, Any]] = []
    limit = max(5, min(25, int(os.environ.get("REDDIT_OSINT_POST_LIMIT", "15"))))

    for subreddit in _configured_subreddits():
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        try:
            resp = fetch_with_curl(url, timeout=18, headers=headers)
            if not resp or resp.status_code != 200:
                logger.warning(
                    "Reddit r/%s fetch failed: HTTP %s",
                    subreddit,
                    resp.status_code if resp else "no response",
                )
                continue
            parsed = parse_reddit_listing(resp.json(), subreddit)
            for post in parsed:
                link = _post_link(post)
                if not link or link in known_links:
                    continue
                known_links.add(link)
                incoming.append(post)
        except Exception as exc:
            logger.warning("Reddit r/%s parse failed: %s", subreddit, exc)
        time.sleep(0.35)

    merged_posts, added = _merge_reddit_posts(existing_posts, incoming)
    merged_posts = apply_reddit_posts_translations(merged_posts)
    geolocated = sum(1 for p in merged_posts if p.get("coords"))
    adversarial = sum(1 for p in merged_posts if p.get("narrative_profile") == "adversarial")

    payload = {
        "posts": merged_posts,
        "total": len(merged_posts),
        "geolocated": geolocated,
        "adversarial_count": adversarial,
        "timestamp": _utcnow().isoformat(),
        "subreddits": _configured_subreddits(),
        "last_fetch_new": added,
        "max_age_days": reddit_max_age_days(),
    }

    with _data_lock:
        latest_data["reddit_osint"] = payload
    _mark_fresh("reddit_osint")
    logger.info(
        "Reddit OSINT: +%s new, %s retained (%s geolocated, %s adversarial-tagged, <=%sd)",
        added,
        len(merged_posts),
        geolocated,
        adversarial,
        reddit_max_age_days(),
    )
    return payload