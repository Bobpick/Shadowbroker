#!/usr/bin/env python3
"""
Delaney Hall case study — sandbox retrospective keyword probe.

Default event: detainee hunger + labor strike began 2026-05-22 (Newark, NJ).
Window: 30 days before strike start → 1 day after (UTC).

Uses PullPush.io Reddit archive (live reddit.com often 403/429 from servers).
Falls back to live Reddit search when archive returns nothing.

Examples:
  # May 2026 strike (recent — archive may lag)
  python3 scripts/sandbox/delaney_hall_case_study.py

  # May 2025 Baraka-arrest / vigil wave (archive-rich benchmark)
  python3 scripts/sandbox/delaney_hall_case_study.py --event-start 2025-05-09
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"
USER_AGENT = "ShadowbrokerDelaneyCaseStudy/1.0 (sandbox research)"

LOCATION_TERMS = (
    "delaney hall",
    "delaney",
    "doremus avenue",
    "doremus ave",
    "newark detention",
    "newark ice",
    "geo group newark",
    "newark migrant",
    "newark jail",
)

MOBILIZATION_TERMS = (
    "protest scheduled",
    "hunger strike",
    "labor strike",
    "general strike",
    "direct action",
    "protest",
    "demonstration",
    "rally",
    "vigil",
    "organizing",
    "mobiliz",
    "day of action",
    "blockade",
    "sit-in",
    "sit in",
    "march",
    "tasks for freedom",
)

ACTOR_TERMS = (
    "ras baraka",
    "first friends",
    "lahuelga",
    "geo group",
    "detainee",
    "immigration detention",
    "nj50501",
    "pax christi",
)

ARCHIVE_SUBREDDITS = (
    "NJ50501",
    "GreenAndPleasant",
    "Political_Revolution",
    "demsocialists",
    "EyesOnIce",
    "EyesOnICEBaltimore",
    "EyesOnICE_Protest",
    "eyesoniceoregon",
    "DemocraticSocialism",
    "dsa",
    "oregon",
    "Newark",
    "newjersey",
    "ProtestFinderUSA",
    "50501",
    "New_Jersey_Politics",
    "DSA",
    "Anarchism",
)

ARCHIVE_QUERIES = (
    "protest scheduled",
    "delaney hall",
    "delaney hall protest",
    "delaney hall vigil",
    "delaney hall strike",
    "ras baraka delaney",
    "newark detention",
)


@dataclass
class Hit:
    term: str
    category: str


@dataclass
class PostRecord:
    platform: str
    source: str
    title: str
    link: str
    published: str
    published_ts: float
    body_excerpt: str
    hits: list[Hit] = field(default_factory=list)
    in_window: bool = False
    location_hit: bool = False
    mobilization_hit: bool = False
    pre_event: bool = False
    strike_day: bool = False

    @property
    def score(self) -> int:
        loc = sum(1 for h in self.hits if h.category == "location")
        mob = sum(1 for h in self.hits if h.category == "mobilization")
        actor = sum(1 for h in self.hits if h.category == "actor")
        bonus = 5 if (self.location_hit and self.mobilization_hit) else 0
        return loc * 2 + mob * 2 + actor + bonus


@dataclass
class CaseWindow:
    event_start: datetime
    window_start: datetime
    window_end: datetime

    @property
    def after_ts(self) -> int:
        return int(self.window_start.timestamp())

    @property
    def before_ts(self) -> int:
        return int(self.window_end.timestamp())

    @property
    def event_ts(self) -> float:
        return self.event_start.timestamp()


def _build_window(event_start: datetime) -> CaseWindow:
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    return CaseWindow(
        event_start=event_start,
        window_start=event_start - timedelta(days=30),
        window_end=event_start + timedelta(days=1, hours=23, minutes=59, seconds=59),
    )


def _classify_hits(text: str) -> list[Hit]:
    lower = text.lower()
    hits: list[Hit] = []
    seen: set[str] = set()

    def add(term: str, category: str) -> None:
        if term in seen:
            return
        seen.add(term)
        hits.append(Hit(term=term, category=category))

    for term in LOCATION_TERMS:
        if term in lower:
            add(term, "location")
    for term in MOBILIZATION_TERMS:
        if term in lower:
            add(term, "mobilization")
    for term in ACTOR_TERMS:
        if term in lower:
            add(term, "actor")
    return hits


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pullpush(params: dict, *, retries: int = 4) -> list[dict]:
    url = PULLPUSH + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            return list(payload.get("data") or [])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            wait = 2 ** attempt
            print(f"  [pullpush retry {attempt + 1}] {exc} — sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
    return []


def _post_from_pullpush(row: dict, *, source: str, window: CaseWindow) -> PostRecord | None:
    title = str(row.get("title") or "").strip()
    body = str(row.get("selftext") or "").strip()
    text = "\n".join(part for part in (title, body) if part)
    hits = _classify_hits(text)
    if not hits:
        return None

    ts = float(row.get("created_utc") or 0)
    permalink = str(row.get("permalink") or "").strip()
    link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
    sub = str(row.get("subreddit") or "").strip()

    location_hit = any(h.category == "location" for h in hits)
    mobilization_hit = any(h.category == "mobilization" for h in hits)
    in_window = window.after_ts <= ts <= window.before_ts

    return PostRecord(
        platform="reddit",
        source=source or f"r/{sub}",
        title=title[:220],
        link=link,
        published=_fmt_ts(ts),
        published_ts=ts,
        body_excerpt=text.replace("\n", " ")[:320],
        hits=hits,
        in_window=in_window,
        location_hit=location_hit,
        mobilization_hit=mobilization_hit,
        pre_event=in_window and ts < window.event_ts,
        strike_day=in_window and window.event_ts <= ts <= window.event_ts + 86400,
    )


def collect_pullpush(window: CaseWindow, *, delay: float = 1.2) -> tuple[list[PostRecord], list[str]]:
    records: dict[str, PostRecord] = {}
    notes: list[str] = []

    def absorb(rows: list[dict], source: str) -> None:
        for row in rows:
            post = _post_from_pullpush(row, source=source, window=window)
            if not post or not post.link:
                continue
            prev = records.get(post.link)
            if prev is None or post.score > prev.score:
                records[post.link] = post

    # Subreddit timelines in window
    for idx, sub in enumerate(ARCHIVE_SUBREDDITS):
        if idx:
            time.sleep(delay)
        rows = _pullpush(
            {
                "subreddit": sub,
                "after": window.after_ts,
                "before": window.before_ts,
                "size": 100,
                "sort": "asc",
                "sort_type": "created_utc",
            }
        )
        if rows:
            notes.append(f"r/{sub}: {len(rows)} raw posts in window")
        absorb(rows, f"r/{sub}")

    # Keyword searches in window
    for idx, query in enumerate(ARCHIVE_QUERIES):
        time.sleep(delay)
        rows = _pullpush(
            {
                "q": query,
                "after": window.after_ts,
                "before": window.before_ts,
                "size": 50,
                "sort": "asc",
                "sort_type": "created_utc",
            }
        )
        if rows:
            notes.append(f"search '{query}': {len(rows)} hits")
        absorb(rows, f"search:{query}")

    return list(records.values()), notes


def _print_report(posts: list[PostRecord], window: CaseWindow, notes: list[str]) -> None:
    in_window = [p for p in posts if p.in_window]
    in_window.sort(key=lambda p: (p.published_ts, -p.score))
    pre_actionable = [
        p for p in in_window if p.pre_event and p.location_hit and p.mobilization_hit
    ]
    pre_location = [p for p in in_window if p.pre_event and p.location_hit]
    strike_day = [p for p in in_window if p.strike_day]

    print("=" * 78)
    print("DELANEY HALL CASE STUDY (sandbox / PullPush archive)")
    print("=" * 78)
    print(f"Event start:  {window.event_start.date().isoformat()}")
    print(f"Window (UTC): {window.window_start.date().isoformat()} → {window.window_end.date().isoformat()}")
    print(f"              (30 days before event → end of day after event start)")
    print()
    print(f"Matched posts (any criteria):        {len(posts)}")
    print(f"In window:                           {len(in_window)}")
    print(f"Pre-event w/ location mention:       {len(pre_location)}")
    print(f"Pre-event location + mobilization:   {len(pre_actionable)}  ← early-warning candidates")
    print(f"Event day (+24h):                    {len(strike_day)}")
    print()

    if pre_actionable:
        print("── Pre-event actionable (before event, location + mobilization terms) ──")
        for p in pre_actionable:
            terms = sorted({f"{h.category}:{h.term}" for h in p.hits})
            print(f"  [{p.published}] score={p.score} {p.source}")
            print(f"    {p.title}")
            print(f"    {terms}")
            print(f"    {p.link}")
            print()

    print("── Timeline (all in-window matches) ──")
    for p in in_window:
        terms = sorted({f"{h.category}:{h.term}" for h in p.hits})
        phase = "PRE-EVENT" if p.pre_event else ("STRIKE-DAY" if p.strike_day else "IN-WINDOW")
        print(f"  [{p.published}] {phase:10} score={p.score} {p.source}")
        print(f"    {p.title[:110]}")
        print(f"    {terms}")
        print(f"    {p.link}")
        print()

    if notes:
        print("── Archive fetch notes ──")
        for note in notes:
            print(f"  {note}")

    if not in_window:
        print()
        print("No indexed Reddit posts in this window.")
        print("Try --event-start 2025-05-09 for the archive-rich May 2025 vigil wave,")
        print("or re-run later for May 2026 once PullPush indexes newer posts.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Delaney Hall retrospective case study")
    parser.add_argument(
        "--event-start",
        default="2026-05-22",
        help="Protest/strike start date YYYY-MM-DD (default: 2026-05-22 hunger strike)",
    )
    parser.add_argument("--export", type=Path, help="JSON output path")
    parser.add_argument("--delay", type=float, default=1.2, help="Delay between PullPush calls")
    args = parser.parse_args()

    y, m, d = map(int, args.event_start.split("-"))
    window = _build_window(datetime(y, m, d, tzinfo=timezone.utc))

    posts, notes = collect_pullpush(window, delay=args.delay)
    _print_report(posts, window, notes)

    payload = {
        "case": "delaney_hall",
        "event_start_utc": window.event_start.isoformat(),
        "window_start_utc": window.window_start.isoformat(),
        "window_end_utc": window.window_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "matched": len(posts),
            "in_window": sum(1 for p in posts if p.in_window),
            "pre_event_actionable": sum(
                1 for p in posts
                if p.pre_event and p.location_hit and p.mobilization_hit
            ),
        },
        "notes": notes,
        "posts": [asdict(p) for p in sorted(posts, key=lambda x: (-x.score, -x.published_ts))],
    }

    out = args.export
    if out is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_DIR / (
            f"delaney_hall_{args.event_start.replace('-', '')}_"
            f"{datetime.now(timezone.utc).strftime('%H%M%SZ')}.json"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"JSON report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())