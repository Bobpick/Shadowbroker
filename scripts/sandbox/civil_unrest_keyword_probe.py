#!/usr/bin/env python3
"""
Sandbox probe: test civil-unrest keyword + source-name matching on live
Telegram (public t.me/s) and Reddit feeds — isolated from Shadowbroker runtime.

Usage:
  python3 scripts/sandbox/civil_unrest_keyword_probe.py
  python3 scripts/sandbox/civil_unrest_keyword_probe.py --config path/to/config.json
  python3 scripts/sandbox/civil_unrest_keyword_probe.py --reddit-only
  python3 scripts/sandbox/civil_unrest_keyword_probe.py --telegram-only

Writes a JSON report to scripts/sandbox/output/ (gitignored pattern: local only).
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "civil_unrest_probe_config.json"
OUTPUT_DIR = SCRIPT_DIR / "output"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from reddit_multireddit import fetch_multireddit_posts, normalize_multireddit_path

USER_AGENT = (
    "Mozilla/5.0 (compatible; ShadowbrokerSandboxProbe/1.0; "
    "+https://github.com/Bobpick/Shadowbroker) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"

# Minimal Telegram HTML parsing (mirrors production regexes, no backend imports).
_TG_MESSAGE_BLOCK_RE = re.compile(
    r'<div class="tgme_widget_message_wrap js-widget_message_wrap"[\s\S]*?</div>\s*</div>\s*</div>',
    re.IGNORECASE,
)
_TG_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>',
    re.IGNORECASE,
)
_TG_DATE_RE = re.compile(
    r'<a class="tgme_widget_message_date" href="(https://t\.me/[^"]+)".*?<time datetime="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class KeywordHit:
    keyword: str
    category: str
    where: str  # body | source_name


@dataclass
class PostMatch:
    platform: str
    source: str
    title: str
    link: str
    published: str
    body_excerpt: str
    hits: list[KeywordHit] = field(default_factory=list)
    source_name_match: bool = False
    matched_source_patterns: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        body_hits = {h.keyword for h in self.hits if h.where == "body"}
        return len(body_hits) + (3 if self.source_name_match else 0)


@dataclass
class SourceProbeResult:
    platform: str
    source: str
    ok: bool
    posts_fetched: int
    error: str | None = None
    matches: list[PostMatch] = field(default_factory=list)


def _load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _http_get(url: str, *, timeout: int, accept: str) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return html_lib.unescape(cleaned).strip()


def _flatten_keywords(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for category, words in (cfg.get("keywords") or {}).items():
        for word in words:
            key = str(word).strip().lower()
            if key:
                out.append((category, key))
    return out


def _match_keywords(text: str, keywords: list[tuple[str, str]]) -> list[KeywordHit]:
    lower = text.lower()
    hits: list[KeywordHit] = []
    seen: set[str] = set()
    for category, keyword in keywords:
        if keyword in seen:
            continue
        # Multi-word phrases: substring. Short tokens: word boundary when alphanumeric.
        if " " in keyword or len(keyword) <= 3:
            found = keyword in lower
        else:
            found = bool(re.search(r"\b" + re.escape(keyword) + r"\b", lower))
        if found:
            hits.append(KeywordHit(keyword=keyword, category=category, where="body"))
            seen.add(keyword)
    return hits


def _match_source_name(source_slug: str, patterns: list[str]) -> list[str]:
    slug = source_slug.lower().strip().lstrip("r/").lstrip("@")
    matched = []
    for pattern in patterns:
        p = str(pattern).strip().lower()
        if p and p in slug:
            matched.append(p)
    return matched


def _parse_telegram_html(html: str, channel: str, *, limit: int) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for block in _TG_MESSAGE_BLOCK_RE.findall(html or ""):
        text_match = _TG_TEXT_RE.search(block)
        if not text_match:
            continue
        text = _strip_html(text_match.group(1))
        if len(text) < 10:
            continue
        date_match = _TG_DATE_RE.search(block)
        link = date_match.group(1) if date_match else f"https://t.me/{channel}"
        published = date_match.group(2) if date_match else ""
        title = text.split("\n", 1)[0][:160]
        posts.append(
            {
                "title": title,
                "body": text[:2000],
                "link": link,
                "published": published,
            }
        )
    return posts[-limit:]


def _parse_reddit_json(payload: dict[str, Any], subreddit: str) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for child in ((payload.get("data") or {}).get("children") or []):
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        selftext = str(data.get("selftext") or "").strip()
        body = "\n".join(part for part in (title, selftext) if part).strip()
        if len(body) < 12:
            continue
        permalink = str(data.get("permalink") or "").strip()
        link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        created = data.get("created_utc")
        if isinstance(created, (int, float)):
            published = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
        else:
            published = ""
        posts.append(
            {
                "title": title[:200],
                "body": body[:2000],
                "link": link or f"https://www.reddit.com/r/{subreddit}/",
                "published": published,
            }
        )
    return posts


def _parse_reddit_rss(xml_text: str) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return posts

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        summary = _strip_html(summary)
        body = "\n".join(part for part in (title, summary) if part).strip()
        if len(body) < 12:
            continue
        published = (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip()
        posts.append(
            {
                "title": title[:200],
                "body": body[:2000],
                "link": link,
                "published": published,
            }
        )
    return posts


def _parse_pullpush_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        selftext = str(row.get("selftext") or "").strip()
        body = "\n".join(part for part in (title, selftext) if part).strip()
        if len(body) < 12:
            continue
        permalink = str(row.get("permalink") or "").strip()
        link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        created = row.get("created_utc")
        if isinstance(created, (int, float)):
            published = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
        else:
            published = ""
        sub = str(row.get("subreddit") or "").strip()
        posts.append(
            {
                "title": title[:200],
                "body": body[:2000],
                "link": link or (f"https://www.reddit.com/r/{sub}/" if sub else ""),
                "published": published,
            }
        )
    return posts


def _fetch_reddit_pullpush(
    query: str,
    *,
    subreddit: str | None,
    limit: int,
    timeout: int,
) -> tuple[list[dict[str, str]], str | None]:
    params: dict[str, str | int] = {
        "q": query,
        "size": min(limit, 100),
        "sort": "desc",
        "sort_type": "created_utc",
    }
    if subreddit:
        params["subreddit"] = subreddit.strip().lstrip("r/")
    url = PULLPUSH + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [], str(exc)
    rows = list(payload.get("data") or [])
    posts = _parse_pullpush_rows(rows)
    if not posts:
        return [], "PullPush returned 0 posts"
    return posts, None


def _fetch_reddit_sub(subreddit: str, *, limit: int, timeout: int) -> tuple[list[dict[str, str]], str | None]:
    sub = subreddit.strip().lstrip("r/")
    json_url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}"
    status, body = _http_get(json_url, timeout=timeout, accept="application/json")
    if status == 200:
        try:
            posts = _parse_reddit_json(json.loads(body), sub)
            if posts:
                return posts, None
        except json.JSONDecodeError as exc:
            return [], f"JSON decode error: {exc}"

    for rss_base in (f"https://www.reddit.com/r/{sub}/.rss", f"https://old.reddit.com/r/{sub}/new/.rss"):
        status, body = _http_get(rss_base, timeout=timeout, accept="application/atom+xml, */*")
        if status == 200:
            posts = _parse_reddit_rss(body)
            if posts:
                return posts, None
    return [], f"HTTP {status} on JSON and RSS (incl. old.reddit)"


def _fetch_telegram_channel(channel: str, *, limit: int, timeout: int) -> tuple[list[dict[str, str]], str | None]:
    slug = channel.strip().lstrip("@")
    url = f"https://t.me/s/{slug}"
    status, body = _http_get(url, timeout=timeout, accept="text/html")
    if status != 200:
        return [], f"HTTP {status}"
    posts = _parse_telegram_html(body, slug, limit=limit)
    if not posts:
        return [], "HTML parsed but 0 posts (channel empty or layout changed)"
    return posts, None


def _analyze_posts(
    *,
    platform: str,
    source: str,
    posts: list[dict[str, str]],
    keywords: list[tuple[str, str]],
    source_patterns: list[str],
) -> list[PostMatch]:
    source_patterns_hit = _match_source_name(source, source_patterns)
    source_name_match = bool(source_patterns_hit)
    matches: list[PostMatch] = []

    for post in posts:
        body = post.get("body") or ""
        title = post.get("title") or ""
        haystack = f"{title}\n{body}"
        hits = _match_keywords(haystack, keywords)
        if source_name_match:
            for pattern in source_patterns_hit:
                hits.append(
                    KeywordHit(keyword=f"source:{pattern}", category="source_name", where="source_name")
                )
        if not hits:
            continue
        matches.append(
            PostMatch(
                platform=platform,
                source=source,
                title=title,
                link=post.get("link") or "",
                published=post.get("published") or "",
                body_excerpt=body[:280].replace("\n", " "),
                hits=hits,
                source_name_match=source_name_match,
                matched_source_patterns=source_patterns_hit,
            )
        )
    return matches


def _probe_reddit(cfg: dict[str, Any], keywords: list[tuple[str, str]], patterns: list[str]) -> list[SourceProbeResult]:
    fetch_cfg = cfg.get("fetch") or {}
    limit = int(fetch_cfg.get("reddit_post_limit", 15))
    timeout = int(fetch_cfg.get("request_timeout_sec", 20))
    delay = float(fetch_cfg.get("delay_between_sources_sec", 3))
    results: list[SourceProbeResult] = []

    for idx, sub in enumerate(cfg.get("reddit_subreddits") or []):
        if idx > 0 and delay > 0:
            time.sleep(delay)
        posts, err = _fetch_reddit_sub(str(sub), limit=limit, timeout=timeout)
        matches = _analyze_posts(
            platform="reddit",
            source=f"r/{str(sub).lstrip('r/')}",
            posts=posts,
            keywords=keywords,
            source_patterns=patterns,
        ) if posts else []
        results.append(
            SourceProbeResult(
                platform="reddit",
                source=f"r/{str(sub).lstrip('r/')}",
                ok=err is None,
                posts_fetched=len(posts),
                error=err,
                matches=matches,
            )
        )
    return results


def _probe_reddit_multireddit(
    cfg: dict[str, Any],
    keywords: list[tuple[str, str]],
    patterns: list[str],
) -> list[SourceProbeResult]:
    fetch_cfg = cfg.get("fetch") or {}
    limit = int(fetch_cfg.get("reddit_post_limit", 15))
    timeout = int(fetch_cfg.get("request_timeout_sec", 20))
    delay = float(fetch_cfg.get("delay_between_sources_sec", 3))
    paths = [
        normalize_multireddit_path(str(path))
        for path in (cfg.get("reddit_multireddits") or [])
        if str(path).strip()
    ]
    if not paths:
        return []

    results: list[SourceProbeResult] = []
    for idx, path in enumerate(paths):
        if idx > 0 and delay > 0:
            time.sleep(delay)
        posts, err = fetch_multireddit_posts(path, limit=limit, timeout=timeout)
        source = f"u/{path}/m/{path.split('/', 1)[-1]}"
        normalized_posts: list[dict[str, str]] = []
        for post in posts:
            normalized_posts.append(
                {
                    "title": str(post.get("title") or ""),
                    "body": str(post.get("body") or ""),
                    "link": str(post.get("link") or ""),
                    "published": str(post.get("published") or ""),
                }
            )
        matches = _analyze_posts(
            platform="reddit",
            source=source,
            posts=normalized_posts,
            keywords=keywords,
            source_patterns=patterns,
        ) if normalized_posts else []
        results.append(
            SourceProbeResult(
                platform="reddit",
                source=source,
                ok=err is None,
                posts_fetched=len(normalized_posts),
                error=err,
                matches=matches,
            )
        )
    return results


def _probe_reddit_search(
    cfg: dict[str, Any],
    keywords: list[tuple[str, str]],
    patterns: list[str],
) -> list[SourceProbeResult]:
    fetch_cfg = cfg.get("fetch") or {}
    limit = int(fetch_cfg.get("reddit_post_limit", 15))
    timeout = int(fetch_cfg.get("request_timeout_sec", 20))
    delay = float(fetch_cfg.get("delay_between_sources_sec", 3))
    queries = [str(q).strip() for q in (cfg.get("reddit_search_queries") or []) if str(q).strip()]
    subs = [str(s).strip() for s in (cfg.get("reddit_search_subreddits") or []) if str(s).strip()]
    if not queries:
        return []

    results: list[SourceProbeResult] = []
    jobs: list[tuple[str, str | None]] = []
    for query in queries:
        jobs.append((query, None))
        for sub in subs:
            jobs.append((query, sub))

    for idx, (query, sub) in enumerate(jobs):
        if idx > 0 and delay > 0:
            time.sleep(delay)
        posts, err = _fetch_reddit_pullpush(query, subreddit=sub, limit=limit, timeout=timeout)
        if sub:
            source = f"search:r/{sub.lstrip('r/')}:{query}"
        else:
            source = f"search:{query}"
        matches = _analyze_posts(
            platform="reddit",
            source=source,
            posts=posts,
            keywords=keywords,
            source_patterns=patterns,
        ) if posts else []
        results.append(
            SourceProbeResult(
                platform="reddit",
                source=source,
                ok=err is None,
                posts_fetched=len(posts),
                error=err,
                matches=matches,
            )
        )
    return results


def _probe_telegram(cfg: dict[str, Any], keywords: list[tuple[str, str]], patterns: list[str]) -> list[SourceProbeResult]:
    fetch_cfg = cfg.get("fetch") or {}
    limit = int(fetch_cfg.get("telegram_bootstrap_posts", 12))
    timeout = int(fetch_cfg.get("request_timeout_sec", 20))
    delay = float(fetch_cfg.get("delay_between_sources_sec", 3))
    results: list[SourceProbeResult] = []

    for idx, channel in enumerate(cfg.get("telegram_channels") or []):
        if idx > 0 and delay > 0:
            time.sleep(delay)
        posts, err = _fetch_telegram_channel(str(channel), limit=limit, timeout=timeout)
        matches = _analyze_posts(
            platform="telegram",
            source=f"t.me/{str(channel).lstrip('@')}",
            posts=posts,
            keywords=keywords,
            source_patterns=patterns,
        ) if posts else []
        results.append(
            SourceProbeResult(
                platform="telegram",
                source=f"t.me/{str(channel).lstrip('@')}",
                ok=err is None,
                posts_fetched=len(posts),
                error=err,
                matches=matches,
            )
        )
    return results


def _body_hits(match: PostMatch) -> list[str]:
    return sorted({h.keyword for h in match.hits if h.where == "body"})


def _print_report(
    results: list[SourceProbeResult],
    keywords: list[tuple[str, str]],
    *,
    actionable_only: bool,
) -> None:
    total_posts = sum(r.posts_fetched for r in results)
    all_matches = [m for r in results for m in r.matches]
    actionable = [m for m in all_matches if _body_hits(m)]
    total_matches = len(actionable) if actionable_only else len(all_matches)
    ok_sources = sum(1 for r in results if r.ok)
    keyword_counts: dict[str, int] = {}

    print("=" * 72)
    print("CIVIL UNREST KEYWORD PROBE (sandbox)")
    print("=" * 72)
    print(f"Sources probed: {len(results)} ({ok_sources} OK)")
    print(f"Posts fetched:  {total_posts}")
    print(
        f"Posts w/ hits:  {total_matches}"
        + (" (body keyword required)" if actionable_only else " (incl. source-name-only)")
    )
    print(f"Actionable (body keyword): {len(actionable)}")
    print(f"Keywords tested: {len(keywords)}")
    print()

    for result in results:
        status = "OK" if result.ok else f"FAIL ({result.error})"
        print(f"[{result.platform.upper():8}] {result.source:24} {status:28} posts={result.posts_fetched}")
        shown = [
            m for m in result.matches
            if not actionable_only or _body_hits(m)
        ]
        if not shown:
            continue
        for match in sorted(shown, key=lambda m: m.score, reverse=True):
            hit_words = _body_hits(match)
            src_tag = f" source_patterns={match.matched_source_patterns}" if match.source_name_match else ""
            print(f"  score={match.score:2}  hits={hit_words}{src_tag}")
            print(f"    {match.title[:90]}")
            if hit_words:
                print(f"    excerpt: {match.body_excerpt[:120]}...")
            print(f"    {match.link}")
            for h in match.hits:
                if h.where == "body":
                    keyword_counts[h.keyword] = keyword_counts.get(h.keyword, 0) + 1

    print()
    print("Top body keywords:")
    for kw, count in sorted(keyword_counts.items(), key=lambda x: (-x[1], x[0]))[:20]:
        print(f"  {count:3}x  {kw}")

    failed = [r for r in results if not r.ok]
    if failed:
        print()
        print("Failed sources (tune channel/sub list):")
        for r in failed:
            print(f"  {r.platform} {r.source}: {r.error}")


def _serialize_results(results: list[SourceProbeResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        out.append(
            {
                **{k: v for k, v in asdict(r).items() if k != "matches"},
                "matches": [asdict(m) for m in r.matches],
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandbox civil-unrest keyword probe")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--reddit-only", action="store_true")
    parser.add_argument("--telegram-only", action="store_true")
    parser.add_argument("--no-write", action="store_true", help="Skip JSON output file")
    parser.add_argument(
        "--actionable-only",
        action="store_true",
        help="Only show posts with at least one body keyword hit (ignore source-name-only)",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config not found: {args.config}", file=sys.stderr)
        return 1

    cfg = _load_config(args.config)
    keywords = _flatten_keywords(cfg)
    patterns = [str(p).strip() for p in (cfg.get("source_name_patterns") or []) if str(p).strip()]

    results: list[SourceProbeResult] = []
    if not args.telegram_only:
        results.extend(_probe_reddit_multireddit(cfg, keywords, patterns))
        results.extend(_probe_reddit(cfg, keywords, patterns))
        results.extend(_probe_reddit_search(cfg, keywords, patterns))
    if not args.reddit_only:
        results.extend(_probe_telegram(cfg, keywords, patterns))

    _print_report(results, keywords, actionable_only=args.actionable_only)

    if not args.no_write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = OUTPUT_DIR / f"civil_unrest_probe_{stamp}.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": str(args.config),
            "summary": {
                "sources": len(results),
                "sources_ok": sum(1 for r in results if r.ok),
                "posts_fetched": sum(r.posts_fetched for r in results),
                "posts_with_hits": sum(len(r.matches) for r in results),
            },
            "results": _serialize_results(results),
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"JSON report: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())