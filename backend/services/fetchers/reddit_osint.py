"""Reddit OSINT — public subreddit listings with keyword geoparsing."""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser

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


def _reddit_request_headers() -> dict[str, str]:
    """Reddit blocks custom bot User-Agents on .json; use a browser-like identity."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; ShadowbrokerOSINT/1.0; "
            f"+https://shadowbroker.local; {outbound_user_agent('reddit-osint')})"
        ),
        "Accept": "application/json, application/atom+xml, application/rss+xml, */*;q=0.8",
    }


def _normalize_reddit_post(
    *,
    subreddit: str,
    title: str,
    body: str,
    link: str,
    published: str,
    author: str = "",
    reddit_score: int = 0,
) -> dict[str, Any] | None:
    clean_title = str(title or "").strip()
    clean_body = "\n".join(part for part in (clean_title, str(body or "").strip()) if part).strip()
    if len(clean_title) < 8 or len(clean_body) < 12:
        return None
    clean_link = str(link or "").strip()
    if not clean_link:
        return None

    sub = str(subreddit or "").strip()
    text_for_geo = clean_body[:1600]
    coords = _resolve_telegram_coords(text_for_geo)
    post_id = hashlib.sha1(f"{clean_link}|{published}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": post_id,
        "title": clean_title[:200],
        "description": clean_body[:1200],
        "link": clean_link,
        "published": published,
        "source": f"r/{sub}",
        "subreddit": sub,
        "author": author,
        "reddit_score": int(reddit_score or 0),
        "risk_score": _score_risk(text_for_geo),
        "narrative_profile": _narrative_profile(sub),
        "coords": [coords[0], coords[1]] if coords else None,
    }


def parse_reddit_rss(payload: str, subreddit: str) -> list[dict[str, Any]]:
    """Parse Reddit Atom/RSS feed when JSON listings are blocked."""
    feed = feedparser.parse(str(payload or ""))
    posts: list[dict[str, Any]] = []

    for entry in feed.entries or []:
        title = str(getattr(entry, "title", "") or "").strip()
        link = str(getattr(entry, "link", "") or "").strip()
        summary = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
        published_raw = (
            getattr(entry, "published", None)
            or getattr(entry, "updated", None)
            or _utcnow().isoformat()
        )
        published_dt = _parse_published_at(published_raw)
        published = published_dt.isoformat() if published_dt else str(published_raw)

        author_name = ""
        author = getattr(entry, "author", None)
        if isinstance(author, str) and author.strip():
            author_name = author.strip().lstrip("/u/")
        elif hasattr(entry, "authors") and entry.authors:
            author_name = str(entry.authors[0].get("name", "")).strip().lstrip("/u/")

        post = _normalize_reddit_post(
            subreddit=subreddit,
            title=title,
            body=summary,
            link=link,
            published=published,
            author=author_name,
        )
        if post:
            posts.append(post)

    return prune_reddit_posts(posts)


def parse_reddit_listing(payload: dict[str, Any], subreddit: str) -> list[dict[str, Any]]:
    """Parse Reddit /new.json listing into normalized post dicts."""
    children = ((payload.get("data") or {}).get("children") or [])
    posts: list[dict[str, Any]] = []

    for child in children:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        selftext = str(data.get("selftext") or "").strip()
        created = data.get("created_utc")
        if isinstance(created, (int, float)):
            published = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
        else:
            published = _utcnow().isoformat()

        permalink = str(data.get("permalink") or "").strip()
        link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        sub = str(data.get("subreddit") or subreddit or "").strip()
        post = _normalize_reddit_post(
            subreddit=sub,
            title=title,
            body="\n".join(part for part in (title, selftext) if part),
            link=link,
            published=published,
            author=str(data.get("author") or ""),
            reddit_score=int(data.get("score") or 0),
        )
        if post:
            posts.append(post)

    return prune_reddit_posts(posts)


def _fetch_subreddit_posts(subreddit: str, *, limit: int, headers: dict[str, str]) -> list[dict[str, Any]]:
    json_url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
    try:
        resp = fetch_with_curl(json_url, timeout=18, headers=headers)
        if resp and resp.status_code == 200:
            return parse_reddit_listing(resp.json(), subreddit)
        if resp and resp.status_code not in {403, 429, 500, 503}:
            logger.warning(
                "Reddit r/%s JSON fetch failed: HTTP %s",
                subreddit,
                resp.status_code,
            )
    except Exception as exc:
        logger.debug("Reddit r/%s JSON parse failed: %s", subreddit, exc)

    rss_url = f"https://www.reddit.com/r/{subreddit}/.rss"
    try:
        rss_headers = dict(headers)
        rss_headers["Accept"] = "application/atom+xml, application/rss+xml, */*;q=0.8"
        resp = fetch_with_curl(rss_url, timeout=20, headers=rss_headers)
        if not resp or resp.status_code != 200:
            logger.warning(
                "Reddit r/%s RSS fetch failed: HTTP %s",
                subreddit,
                resp.status_code if resp else "no response",
            )
            return []
        posts = parse_reddit_rss(resp.text, subreddit)
        if posts:
            logger.info("Reddit r/%s: loaded %s posts via RSS fallback", subreddit, len(posts))
        return posts
    except Exception as exc:
        logger.warning("Reddit r/%s RSS parse failed: %s", subreddit, exc)
        return []


def fetch_reddit_osint() -> dict[str, Any]:
    if not is_any_active("reddit_osint"):
        return latest_data.get("reddit_osint") or {"posts": [], "total": 0, "timestamp": None}

    if not reddit_osint_enabled():
        with _data_lock:
            latest_data["reddit_osint"] = {"posts": [], "total": 0, "timestamp": None, "disabled": True}
        _mark_fresh("reddit_osint")
        return latest_data["reddit_osint"]

    headers = _reddit_request_headers()

    with _data_lock:
        prior = latest_data.get("reddit_osint") or {}
        existing_posts = prune_reddit_posts(list(prior.get("posts") or []))

    known_links = {_post_link(post) for post in existing_posts if _post_link(post)}
    incoming: list[dict[str, Any]] = []
    limit = max(5, min(25, int(os.environ.get("REDDIT_OSINT_POST_LIMIT", "15"))))

    for subreddit in _configured_subreddits():
        try:
            parsed = _fetch_subreddit_posts(subreddit, limit=limit, headers=headers)
            for post in parsed:
                link = _post_link(post)
                if not link or link in known_links:
                    continue
                known_links.add(link)
                incoming.append(post)
        except Exception as exc:
            logger.warning("Reddit r/%s fetch failed: %s", subreddit, exc)
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