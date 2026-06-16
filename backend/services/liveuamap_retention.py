"""LiveUAMap incident retention helpers (no Playwright dependency)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_LIVEUAMAP_MAX_AGE_DAYS = 7


def liveuamap_max_age_days() -> int:
    raw = str(os.environ.get("LIVEUAMAP_MAX_AGE_DAYS", "")).strip()
    if not raw:
        return DEFAULT_LIVEUAMAP_MAX_AGE_DAYS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_LIVEUAMAP_MAX_AGE_DAYS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _marker_event_time(marker: dict[str, Any]) -> datetime | None:
    event_time = marker.get("timestamp")
    if event_time is None or event_time == "":
        event_time = marker.get("time") or marker.get("t")
    if event_time is None or event_time == "":
        return None
    try:
        ts = int(event_time)
    except (ValueError, TypeError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def marker_within_retention(
    marker: dict[str, Any],
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> bool:
    published = _marker_event_time(marker)
    if published is None:
        return False
    limit_days = max_age_days if max_age_days is not None else liveuamap_max_age_days()
    cutoff = (now or _utcnow()) - timedelta(days=limit_days)
    return published >= cutoff


def prune_liveuamap_incidents(
    incidents: list[dict[str, Any]],
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Drop LiveUAMap markers older than the configured retention window."""
    return [
        marker
        for marker in incidents
        if marker_within_retention(marker, max_age_days=max_age_days, now=now)
    ]