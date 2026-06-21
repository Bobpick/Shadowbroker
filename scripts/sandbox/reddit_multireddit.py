#!/usr/bin/env python3
"""Resolve and fetch public Reddit multireddits (e.g. /user/bobpick/m/protests/)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html import unescape
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (compatible; ShadowbrokerSandboxProbe/1.0; "
    "+https://github.com/Bobpick/Shadowbroker) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_SUBREDDIT_IN_LINK_RE = re.compile(r"/r/([A-Za-z0-9_]+)/")
_MULTIREDDIT_JSON_RE = re.compile(r'"subreddits"\s*:\s*(\[[\s\S]*?\])')
_TITLE_LINK_RE = re.compile(
    r'<a[^>]*class="title[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


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


def multireddit_page_url(path: str, *, sort: str = "new") -> str:
    user, name = _multireddit_parts(path)
    suffix = f"{sort}/" if sort else ""
    return f"https://old.reddit.com/user/{user}/m/{name}/{suffix}"


def _multireddit_parts(path: str) -> tuple[str, str]:
    normalized = normalize_multireddit_path(path)
    if "/" not in normalized:
        raise ValueError(f"invalid multireddit path: {path!r}")
    user, name = normalized.split("/", 1)
    return user.strip(), name.strip()


def _fetch_html(url: str, *, timeout: int) -> tuple[str | None, str | None]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*;q=0.8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return None, str(exc)


def resolve_multireddit_subs(path: str, *, timeout: int = 25) -> tuple[list[str], str | None]:
    """Return member subreddit names from embedded multireddit JSON on old.reddit."""
    url = multireddit_page_url(path)
    html, err = _fetch_html(url, timeout=timeout)
    if not html:
        return [], err

    match = _MULTIREDDIT_JSON_RE.search(html)
    if not match:
        return [], "multireddit JSON block not found (private feed or layout change)"

    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return [], f"multireddit JSON decode error: {exc}"

    subs: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str((row or {}).get("name") if isinstance(row, dict) else row or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        subs.append(name)
    if not subs:
        return [], "multireddit JSON contained 0 subreddits"
    return subs, None


def _subreddit_from_link(link: str) -> str:
    match = _SUBREDDIT_IN_LINK_RE.search(str(link or ""))
    return match.group(1) if match else ""


def _normalize_post_link(link: str) -> str:
    raw = str(link or "").strip()
    if raw.startswith("/"):
        return f"https://www.reddit.com{raw}"
    return raw


def fetch_multireddit_posts(path: str, *, limit: int = 25, timeout: int = 25) -> tuple[list[dict[str, Any]], str | None]:
    """Parse recent posts from an old.reddit multireddit HTML listing."""
    url = multireddit_page_url(path)
    html, err = _fetch_html(url, timeout=timeout)
    if not html:
        return [], err

    posts: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for link, title in _TITLE_LINK_RE.findall(html):
        full_link = _normalize_post_link(link)
        if not full_link or full_link in seen_links:
            continue
        seen_links.add(full_link)
        clean_title = unescape(re.sub(r"\s+", " ", title)).strip()
        if len(clean_title) < 8:
            continue
        subreddit = _subreddit_from_link(full_link) or _subreddit_from_link(link)
        posts.append(
            {
                "title": clean_title[:200],
                "body": clean_title[:2000],
                "link": full_link,
                "published": "",
                "subreddit": subreddit,
            }
        )
        if len(posts) >= limit:
            break

    if not posts:
        return [], "multireddit HTML parsed but 0 posts found"
    return posts, None


def main() -> int:
    import argparse
    from datetime import datetime, timezone
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Resolve or sample a Reddit multireddit feed")
    parser.add_argument("path", nargs="?", default="bobpick/protests")
    parser.add_argument("--resolve-only", action="store_true")
    parser.add_argument("--export", type=Path, help="Write resolved sub list JSON")
    args = parser.parse_args()

    path = normalize_multireddit_path(args.path)
    subs, err = resolve_multireddit_subs(path)
    if err:
        print(f"resolve failed: {err}", file=sys.stderr)
        return 1
    print(f"multireddit: {path}")
    for sub in subs:
        print(f"  r/{sub}")

    if not args.resolve_only:
        posts, post_err = fetch_multireddit_posts(path, limit=10)
        print(f"\nrecent posts: {len(posts)}" + (f" ({post_err})" if post_err else ""))
        for post in posts[:5]:
            sub = post.get("subreddit") or "?"
            print(f"  r/{sub}: {str(post.get('title') or '')[:90]}")

    if args.export:
        user, name = _multireddit_parts(path)
        payload = {
            "multireddit": path,
            "url": f"https://www.reddit.com/user/{user}/m/{name}/",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "subreddits": subs,
        }
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nexported: {args.export}")
        print(
            "Production uses REDDIT_OSINT_MULTIREDDITS="
            f"{path} (runtime resolve). Rebuild backend after code changes."
        )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())