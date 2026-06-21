"""Resolve and fetch public Reddit multireddits for OSINT ingestion."""

from __future__ import annotations

import json
import logging
import os
import re
from html import unescape
from typing import Any

from services.network_utils import fetch_with_curl, outbound_user_agent

logger = logging.getLogger(__name__)

_SUBREDDIT_IN_LINK_RE = re.compile(r"/r/([A-Za-z0-9_]+)/")
_MULTIREDDIT_JSON_RE = re.compile(r'"subreddits"\s*:\s*(\[[\s\S]*?\])')
_TITLE_LINK_RE = re.compile(
    r'<a[^>]*class="title[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


def configured_multireddits() -> list[str]:
    raw = str(os.environ.get("REDDIT_OSINT_MULTIREDDITS", "")).strip()
    if not raw:
        return []
    return [normalize_multireddit_path(part) for part in raw.split(",") if part.strip()]


def normalize_multireddit_path(value: str) -> str:
    raw = str(value or "").strip().strip("/")
    for prefix in ("https://www.reddit.com/user/", "https://old.reddit.com/user/", "user/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    if raw.startswith("m/"):
        raw = raw[2:]
    if "/m/" in raw:
        user, name = raw.split("/m/", 1)
        return f"{user.strip()}/{name.strip()}"
    return raw


def _multireddit_parts(path: str) -> tuple[str, str]:
    normalized = normalize_multireddit_path(path)
    if "/" not in normalized:
        raise ValueError(f"invalid multireddit path: {path!r}")
    user, name = normalized.split("/", 1)
    return user.strip(), name.strip()


def multireddit_page_url(path: str) -> str:
    user, name = _multireddit_parts(path)
    return f"https://old.reddit.com/user/{user}/m/{name}/"


def _request_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; ShadowbrokerOSINT/1.0; "
            f"+https://shadowbroker.local; {outbound_user_agent('reddit-multireddit')})"
        ),
        "Accept": "text/html,application/json,*/*;q=0.8",
    }


def subreddit_from_link(link: str) -> str:
    match = _SUBREDDIT_IN_LINK_RE.search(str(link or ""))
    return match.group(1) if match else ""


def resolve_multireddit_subs(path: str, *, timeout: int = 25) -> list[str]:
    url = multireddit_page_url(path)
    resp = fetch_with_curl(url, timeout=timeout, headers=_request_headers())
    if not resp or resp.status_code != 200:
        logger.warning(
            "Reddit multireddit %s resolve failed: HTTP %s",
            path,
            resp.status_code if resp else "no response",
        )
        return []

    match = _MULTIREDDIT_JSON_RE.search(str(resp.text or ""))
    if not match:
        logger.warning("Reddit multireddit %s: member list JSON not found", path)
        return []

    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("Reddit multireddit %s JSON decode failed: %s", path, exc)
        return []

    subs: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str((row or {}).get("name") if isinstance(row, dict) else row or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        subs.append(name)
    return subs


def fetch_multireddit_posts(path: str, *, limit: int = 25, timeout: int = 25) -> list[dict[str, Any]]:
    url = multireddit_page_url(path)
    resp = fetch_with_curl(url, timeout=timeout, headers=_request_headers())
    if not resp or resp.status_code != 200:
        logger.warning(
            "Reddit multireddit %s feed failed: HTTP %s",
            path,
            resp.status_code if resp else "no response",
        )
        return []

    posts: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for link, title in _TITLE_LINK_RE.findall(str(resp.text or "")):
        full_link = link if not link.startswith("/") else f"https://www.reddit.com{link}"
        if not full_link or full_link in seen_links:
            continue
        seen_links.add(full_link)
        clean_title = unescape(re.sub(r"\s+", " ", title)).strip()
        if len(clean_title) < 8:
            continue
        posts.append(
            {
                "title": clean_title[:200],
                "body": clean_title[:2000],
                "link": full_link,
                "published": "",
                "subreddit": subreddit_from_link(full_link) or subreddit_from_link(link),
            }
        )
        if len(posts) >= limit:
            break
    return posts