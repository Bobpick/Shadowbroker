"""GDACS global weather/hydro hazards (TC, flood, wildfire, drought)."""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

_GDACS_EVENTLIST = "TC;FL;WF;DR"
_GDACS_SEVERITY = {
    "red": "Extreme",
    "orange": "Severe",
    "green": "Moderate",
}


def _gdacs_severity(alertlevel: str | None) -> str:
    return _GDACS_SEVERITY.get((alertlevel or "").lower(), "Unknown")


def _event_still_relevant(props: dict[str, Any]) -> bool:
    if str(props.get("iscurrent", "")).lower() == "true":
        return True
    todate = props.get("todate") or props.get("fromdate")
    if not todate:
        return False
    try:
        end = datetime.fromisoformat(str(todate).replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return end >= datetime.now(timezone.utc) - timedelta(days=3)
    except ValueError:
        return False


def _fetch_geometry(url: str) -> dict[str, Any] | None:
    if not url:
        return None
    try:
        res = fetch_with_curl(url, timeout=12)
        if res.status_code != 200:
            return None
        payload = res.json()
        features = payload.get("features") or []
        if not features:
            return None
        # Prefer the largest polygon; fall back to first geometry.
        best = None
        best_score = -1
        for feature in features:
            geom = feature.get("geometry")
            if not geom:
                continue
            score = 1
            if geom.get("type") in {"Polygon", "MultiPolygon"}:
                score = 10
            if score > best_score:
                best = geom
                best_score = score
        return best
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("GDACS geometry fetch failed for %s: %s", url, exc)
        return None


def fetch_global_weather_hazards(*, geometry_limit: int = 14) -> list[dict[str, Any]]:
    """Return active GDACS tropical cyclone / flood / wildfire / drought hazards."""
    url = (
        "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
        f"?eventlist={_GDACS_EVENTLIST}&limit=60"
    )
    candidates: list[dict[str, Any]] = []
    try:
        res = fetch_with_curl(url, timeout=20)
        if res.status_code != 200:
            logger.warning("GDACS event list HTTP %s", res.status_code)
            return []
        features = res.json().get("features") or []
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.error("GDACS event list failed: %s", exc)
        return []

    for feature in features:
        props = feature.get("properties") or {}
        if not _event_still_relevant(props):
            continue
        geom = feature.get("geometry")
        eventtype = props.get("eventtype") or "WX"
        eventid = props.get("eventid")
        episodeid = props.get("episodeid")
        candidates.append(
            {
                "id": f"gdacs-{eventtype}-{eventid}-{episodeid}",
                "event": props.get("name") or props.get("description") or eventtype,
                "severity": _gdacs_severity(props.get("alertlevel")),
                "certainty": props.get("episodealertlevel") or "",
                "urgency": "Immediate" if str(props.get("iscurrent")).lower() == "true" else "Expected",
                "headline": props.get("htmldescription") or props.get("description") or "",
                "description": (props.get("description") or "")[:300],
                "expires": props.get("todate") or "",
                "geometry": geom,
                "source": "GDACS",
                "eventtype": eventtype,
                "country": props.get("country") or "",
                "alertlevel": props.get("alertlevel") or "",
                "report_url": (props.get("url") or {}).get("report"),
                "_geometry_url": (props.get("url") or {}).get("geometry"),
                "_needs_geometry": geom is None
                or geom.get("type") not in {"Polygon", "MultiPolygon"},
            }
        )

    # Prioritize live events, then red/orange alert levels.
    candidates.sort(
        key=lambda row: (
            0 if str(row.get("urgency")) == "Immediate" else 1,
            0 if str(row.get("alertlevel")).lower() == "red" else 1,
            0 if str(row.get("alertlevel")).lower() == "orange" else 1,
        )
    )

    to_enrich = [row for row in candidates if row.pop("_needs_geometry")][:geometry_limit]
    if to_enrich:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_fetch_geometry, row.pop("_geometry_url", None)): row
                for row in to_enrich
            }
            for fut in concurrent.futures.as_completed(futures, timeout=20):
                row = futures[fut]
                try:
                    geom = fut.result()
                    if geom:
                        row["geometry"] = geom
                except Exception:  # noqa: BLE001 — optional enrichment
                    pass

    alerts = []
    for row in candidates:
        row.pop("_geometry_url", None)
        if row.get("geometry"):
            alerts.append(row)

    logger.info("GDACS weather hazards: %s active (from %s candidates)", len(alerts), len(candidates))
    return alerts