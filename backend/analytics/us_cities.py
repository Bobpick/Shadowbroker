"""US metro protest watch — city-level GT from Telegram/Reddit OSINT feeds."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# key, lat_min, lat_max, lng_min, lng_max, centroid_lat, centroid_lng, label
_US_METROS: tuple[tuple[str, float, float, float, float, float, float, str], ...] = (
    ("washington_dc", 38.70, 39.10, -77.20, -76.80, 38.907, -77.036, "Washington, DC"),
    ("new_york", 40.40, 41.00, -74.35, -73.60, 40.712, -74.006, "New York City"),
    ("portland", 45.40, 45.65, -122.85, -122.45, 45.515, -122.679, "Portland"),
    ("chicago", 41.60, 42.10, -87.95, -87.50, 41.878, -87.630, "Chicago"),
    ("baltimore", 39.20, 39.45, -76.75, -76.45, 39.290, -76.612, "Baltimore"),
    ("los_angeles", 33.70, 34.35, -118.75, -118.05, 34.052, -118.244, "Los Angeles"),
    ("seattle", 47.40, 47.85, -122.55, -122.15, 47.606, -122.332, "Seattle"),
    ("minneapolis", 44.80, 45.15, -93.45, -93.05, 44.978, -93.265, "Minneapolis"),
    ("atlanta", 33.55, 33.95, -84.65, -84.15, 33.749, -84.388, "Atlanta"),
    ("philadelphia", 39.80, 40.15, -75.35, -74.90, 39.952, -75.165, "Philadelphia"),
    ("san_francisco", 37.70, 37.85, -122.55, -122.35, 37.775, -122.419, "San Francisco"),
    ("oakland", 37.70, 37.90, -122.35, -122.10, 37.805, -122.271, "Oakland"),
    ("austin", 30.10, 30.50, -97.95, -97.55, 30.267, -97.743, "Austin"),
    ("denver", 39.55, 39.90, -105.15, -104.75, 39.739, -104.990, "Denver"),
    ("boston", 42.20, 42.45, -71.20, -70.95, 42.360, -71.058, "Boston"),
    ("houston", 29.50, 30.10, -95.80, -95.00, 29.760, -95.370, "Houston"),
    ("detroit", 42.20, 42.50, -83.30, -82.90, 42.331, -83.046, "Detroit"),
    ("phoenix", 33.20, 33.70, -112.40, -111.70, 33.448, -112.074, "Phoenix"),
    ("miami", 25.50, 26.00, -80.50, -79.90, 25.762, -80.192, "Miami"),
    ("dallas", 32.50, 33.10, -97.10, -96.40, 32.777, -96.797, "Dallas"),
    ("san_diego", 32.50, 33.00, -117.40, -116.90, 32.716, -117.161, "San Diego"),
    ("las_vegas", 35.90, 36.40, -115.40, -114.90, 36.169, -115.140, "Las Vegas"),
    ("nashville", 35.90, 36.40, -87.10, -86.50, 36.163, -86.781, "Nashville"),
    ("new_orleans", 29.80, 30.10, -90.30, -89.90, 29.951, -90.072, "New Orleans"),
    ("st_louis", 38.40, 38.80, -90.50, -89.90, 38.627, -90.199, "St. Louis"),
    ("pittsburgh", 40.20, 40.60, -80.20, -79.70, 40.441, -79.996, "Pittsburgh"),
    ("cleveland", 41.30, 41.70, -82.00, -81.40, 41.499, -81.694, "Cleveland"),
    ("charlotte", 35.00, 35.50, -81.10, -80.60, 35.227, -80.843, "Charlotte"),
    ("kansas_city", 38.80, 39.40, -94.90, -94.20, 39.100, -94.578, "Kansas City"),
    ("milwaukee", 42.80, 43.20, -88.20, -87.60, 43.039, -87.907, "Milwaukee"),
    ("indianapolis", 39.50, 40.00, -86.40, -85.90, 39.768, -86.158, "Indianapolis"),
    ("columbus", 39.70, 40.20, -83.20, -82.70, 39.961, -82.999, "Columbus"),
    ("tampa", 27.70, 28.20, -82.80, -82.20, 27.951, -82.458, "Tampa"),
    ("sacramento", 38.30, 38.80, -121.80, -121.20, 38.582, -121.494, "Sacramento"),
    ("raleigh", 35.50, 36.00, -79.00, -78.40, 35.780, -78.639, "Raleigh"),
    ("san_antonio", 29.20, 29.65, -98.70, -98.30, 29.425, -98.495, "San Antonio"),
    ("memphis", 34.95, 35.35, -90.20, -89.75, 35.150, -90.049, "Memphis"),
    ("salt_lake_city", 40.60, 40.90, -112.10, -111.70, 40.761, -111.891, "Salt Lake City"),
    ("richmond", 37.40, 37.65, -77.60, -77.30, 37.541, -77.436, "Richmond"),
)

_US_METRO_BY_KEY = {row[0]: row for row in _US_METROS}

_US_CITY_ALIASES: dict[str, str] = {
    "dc": "washington_dc",
    "d.c.": "washington_dc",
    "washington dc": "washington_dc",
    "washington, dc": "washington_dc",
    "nyc": "new_york",
    "new york city": "new_york",
    "manhattan": "new_york",
    "brooklyn": "new_york",
    "la": "los_angeles",
    "sf": "san_francisco",
    "bay area": "san_francisco",
    "twin cities": "minneapolis",
    "philly": "philadelphia",
    "st. louis": "st_louis",
    "st louis": "st_louis",
    "new orleans": "new_orleans",
    "nola": "new_orleans",
    "kc": "kansas_city",
    "kansas city": "kansas_city",
    "vegas": "las_vegas",
    "lv": "las_vegas",
    "san diego": "san_diego",
    "san antonio": "san_antonio",
    "salt lake": "salt_lake_city",
    "salt lake city": "salt_lake_city",
    "slc": "salt_lake_city",
    "fort worth": "dallas",
    "dfw": "dallas",
    "queens": "new_york",
    "bronx": "new_york",
}

_SOURCE_CITY_HINTS: dict[str, str] = {
    "portlanddsa": "portland",
    "nycdsa": "new_york",
    "chicagodsa": "chicago",
    "phillydsa": "philadelphia",
    "bostondsa": "boston",
    "seattledsa": "seattle",
    "bayareadsa": "san_francisco",
    "sfdsa": "san_francisco",
    "dsasf": "san_francisco",
    "atldsa": "atlanta",
    "atlantadsa": "atlanta",
    "houstondsa": "houston",
    "eyesonicebaltimore": "baltimore",
    "eyesoniceoregon": "portland",
    "eyesonice_protest": "washington_dc",
    "eyesonice": "washington_dc",
    "nj50501": "new_york",
    "leftcoastriseup": "portland",
    "climatestrike": "washington_dc",
    "dsausa": "washington_dc",
    "greenandpleasant": "new_york",
    "political_revolution": "washington_dc",
    "demsocialists": "washington_dc",
    "democraticsocialism": "washington_dc",
    "dsa": "washington_dc",
    "directaction": "portland",
}

_MOBILIZATION_HINTS = re.compile(
    r"\b("
    r"protest\s+scheduled|direct\s+action|day\s+of\s+action|general\s+strike|"
    r"mass\s+rally|protest\s+mobil|blockade|sit[\s-]?in|occupation|"
    r"demonstration|rally\s+at|meet\s+at|gather\s+at|march\s+to|picketing|"
    r"civil\s+disobedience|counter[\s-]?protest"
    r")\b",
    re.I,
)

_PROTEST_HINTS = re.compile(
    r"\b(protests?|demonstrat(?:ion|ing)?|rall(?:y|ies)|mobiliz(?:e|ation|ing)?|"
    r"march(?:es|ing)?|vigil|unrest)\b",
    re.I,
)


def us_metro_keys() -> tuple[str, ...]:
    return tuple(row[0] for row in _US_METROS)


def us_city_label(city_key: str) -> str:
    row = _US_METRO_BY_KEY.get(str(city_key or "").strip().lower())
    if row:
        return row[7]
    return str(city_key or "").replace("_", " ").title()


def us_city_centroid(city_key: str) -> tuple[float, float] | None:
    row = _US_METRO_BY_KEY.get(str(city_key or "").strip().lower())
    if not row:
        return None
    return row[5], row[6]


def us_city_from_coords(lat: float, lng: float) -> str | None:
    for key, lat_min, lat_max, lng_min, lng_max, _clat, _clng, _label in _US_METROS:
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return key
    return None


def us_city_from_text(text: str) -> str | None:
    haystack = f" {str(text or '').lower()} "
    for alias, city_key in sorted(_US_CITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if f" {alias} " in haystack:
            return city_key
    for key, _a, _b, _c, _d, _clat, _clng, label in _US_METROS:
        token = label.lower()
        if f" {token} " in haystack:
            return key
        short = key.replace("_", " ")
        if f" {short} " in haystack:
            return key
    return None


def us_city_from_source(source: str) -> str | None:
    raw = str(source or "").strip().lower()
    if not raw:
        return None
    normalized = raw.lstrip("r/").lstrip("@").replace("-", "").replace("_", "")
    for hint, city_key in _SOURCE_CITY_HINTS.items():
        hint_norm = hint.replace("-", "").replace("_", "")
        if hint_norm in normalized or normalized in hint_norm:
            return city_key
    return None


def resolve_us_city(
    *,
    text: str = "",
    coords: Any = None,
    source: str = "",
    region: str = "",
) -> str | None:
    """Best-effort US metro key from feed record fields."""
    region_key = str(region or "").strip().lower()
    if region_key in _US_METRO_BY_KEY:
        return region_key

    source_city = us_city_from_source(source)
    if source_city:
        return source_city

    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lat = float(coords[0])
            lng = float(coords[1])
            city = us_city_from_coords(lat, lng)
            if city:
                return city
        except (TypeError, ValueError):
            pass

    return us_city_from_text(text)


def _parse_published(value: Any) -> datetime | None:
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


def _heatmap_city_scores(heatmap: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for feature in (heatmap or {}).get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        region = str(props.get("region") or "").strip().lower()
        if region not in _US_METRO_BY_KEY:
            city = None
            geometry = feature.get("geometry") or {}
            coords = geometry.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                try:
                    lng = float(coords[0])
                    lat = float(coords[1])
                    city = us_city_from_coords(lat, lng)
                except (TypeError, ValueError):
                    city = None
            if not city:
                continue
            region = city
        unrest = float(props.get("unrest") or 0.0)
        risk = float(props.get("risk") or 0.0)
        scores[region] = {
            "unrest": unrest,
            "risk": risk,
            "conflict": float(props.get("conflict") or 0.0),
            "ignition": bool(props.get("micro_ignition")),
            "risk_delta": float(props.get("risk_delta") or 0.0),
            "updates": int(props.get("updates") or 0),
        }
    return scores


def _scan_feed_posts(
    posts: list[dict[str, Any]],
    *,
    source_kind: str,
    cutoff: datetime,
) -> dict[str, dict[str, Any]]:
    tallies: dict[str, dict[str, Any]] = {}

    for post in posts:
        if not isinstance(post, dict):
            continue
        published = _parse_published(post.get("published"))
        if published is None or published < cutoff:
            continue

        text = "\n".join(
            str(post.get(key) or "").strip()
            for key in ("title", "description", "title_translated", "description_translated")
            if post.get(key)
        ).strip()
        if not text:
            continue

        source = str(post.get("source") or post.get("channel") or post.get("subreddit") or "")
        city = resolve_us_city(
            text=text,
            coords=post.get("coords"),
            source=source,
            region=post.get("region") or "",
        )
        if not city:
            continue

        bucket = tallies.setdefault(
            city,
            {
                "mentions": 0,
                "protest_mentions": 0,
                "mobilization_hits": 0,
                "sources": set(),
                "recent": [],
            },
        )
        bucket["mentions"] += 1
        narrative = str(post.get("narrative_profile") or "").strip().lower()
        if narrative == "protest" or _PROTEST_HINTS.search(text):
            bucket["protest_mentions"] += 1
        if _MOBILIZATION_HINTS.search(text):
            bucket["mobilization_hits"] += 1
        bucket["sources"].add(source or source_kind)
        if len(bucket["recent"]) < 3:
            bucket["recent"].append(
                {
                    "title": str(post.get("title") or "")[:140],
                    "source": source,
                    "published": post.get("published"),
                    "link": post.get("link"),
                }
            )

    return tallies


def _protest_potential(
    *,
    unrest: float,
    risk: float,
    ignition: bool,
    mentions: int,
    protest_mentions: int,
    mobilization_hits: int,
) -> float:
    feed_score = min(1.0, protest_mentions * 0.18 + mobilization_hits * 0.28 + mentions * 0.06)
    gt_score = min(1.0, unrest * 0.55 + risk * 0.25 + (0.12 if ignition else 0.0))
    return round(min(1.0, gt_score * 0.62 + feed_score * 0.38), 4)


def build_us_city_watch(
    *,
    gt_risk: dict[str, Any] | None = None,
    telegram_osint: dict[str, Any] | None = None,
    reddit_osint: dict[str, Any] | None = None,
    lookback_days: int = 7,
    limit: int = 20,
) -> dict[str, Any]:
    """Rank US metros by protest potential from GT unrest + Telegram/Reddit OSINT."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, lookback_days))
    heatmap = (gt_risk or {}).get("heatmap") or {}
    heat_scores = _heatmap_city_scores(heatmap)

    telegram_posts = list((telegram_osint or {}).get("posts") or [])
    reddit_posts = list((reddit_osint or {}).get("posts") or [])
    feed_tallies = _scan_feed_posts(telegram_posts, source_kind="telegram", cutoff=cutoff)
    for city, bucket in _scan_feed_posts(reddit_posts, source_kind="reddit", cutoff=cutoff).items():
        if city not in feed_tallies:
            feed_tallies[city] = bucket
            continue
        merged = feed_tallies[city]
        merged["mentions"] += bucket["mentions"]
        merged["protest_mentions"] += bucket["protest_mentions"]
        merged["mobilization_hits"] += bucket["mobilization_hits"]
        merged["sources"].update(bucket["sources"])
        merged["recent"].extend(bucket["recent"])
        merged["recent"] = merged["recent"][:3]

    cities: list[dict[str, Any]] = []
    candidate_keys = set(_US_METRO_BY_KEY) | set(heat_scores) | set(feed_tallies)

    for city_key in candidate_keys:
        row = _US_METRO_BY_KEY.get(city_key)
        if not row:
            continue
        _key, _a, _b, _c, _d, lat, lng, label = row
        heat = heat_scores.get(city_key, {})
        feed = feed_tallies.get(city_key, {})
        mentions = int(feed.get("mentions") or 0)
        protest_mentions = int(feed.get("protest_mentions") or 0)
        mobilization_hits = int(feed.get("mobilization_hits") or 0)
        unrest = float(heat.get("unrest") or 0.0)
        risk = float(heat.get("risk") or 0.0)
        ignition = bool(heat.get("ignition"))
        potential = _protest_potential(
            unrest=unrest,
            risk=risk,
            ignition=ignition,
            mentions=mentions,
            protest_mentions=protest_mentions,
            mobilization_hits=mobilization_hits,
        )
        if potential < 0.08 and mentions == 0 and unrest < 0.12:
            continue

        cities.append(
            {
                "city": city_key,
                "label": label,
                "lat": lat,
                "lng": lng,
                "protest_potential": potential,
                "unrest": round(unrest, 4),
                "risk": round(risk, 4),
                "ignition": ignition,
                "mentions": mentions,
                "protest_mentions": protest_mentions,
                "mobilization_hits": mobilization_hits,
                "sources": sorted(feed.get("sources") or []),
                "recent_signals": list(feed.get("recent") or []),
            }
        )

    cities.sort(
        key=lambda row: (
            float(row.get("protest_potential") or 0.0),
            int(row.get("mobilization_hits") or 0),
            int(row.get("protest_mentions") or 0),
            float(row.get("unrest") or 0.0),
        ),
        reverse=True,
    )

    return {
        "enabled": True,
        "timestamp": now.isoformat(),
        "lookback_days": lookback_days,
        "cities": cities[: max(1, limit)],
        "tracked_metros": len(_US_METROS),
        "active_metros": len(cities),
    }