"""WastewaterSCAN trend analysis, snapshots, and national rollup."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Geographic center of the contiguous United States (biosurveillance map beacon).
US_SURVEILLANCE_LAT = 39.8283
US_SURVEILLANCE_LNG = -98.5795

TREND_WINDOW_DAYS = 21
SNAPSHOT_RETENTION_DAYS = 90
BASELINE_LOOKBACK_DAYS = 7

ACTIVITY_RANK: dict[str, int] = {
    "not calculated": -1,
    "very low": 0,
    "low": 1,
    "below normal": 2,
    "normal": 3,
    "medium": 4,
    "above normal": 5,
    "high": 6,
    "very high": 7,
}

ALERT_CATEGORIES = {"high", "very high", "above normal"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_dir() -> Path:
    raw = os.environ.get("WASTEWATER_SNAPSHOT_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "wastewater_snapshots"


def _activity_rank(value: Any) -> int:
    return ACTIVITY_RANK.get(str(value or "").strip().lower(), -1)


def _is_alert(activity: Any) -> bool:
    return str(activity or "").strip().lower() in ALERT_CATEGORIES


def _parse_collection_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_pathogen_point(target_data: dict[str, Any]) -> dict[str, Any] | None:
    concentration = target_data.get("gc_g_dry_weight", 0) or 0
    normalized = (
        target_data.get("gc_g_dry_weight_trimmed5_pmmov")
        or target_data.get("gc_g_dry_weight_pmmov")
        or 0
    )
    if concentration <= 0 and normalized <= 0:
        return None
    activity = str(target_data.get("activity_category") or "not calculated")
    return {
        "activity": activity,
        "activity_rank": _activity_rank(activity),
        "alert": _is_alert(activity),
        "concentration": round(float(concentration), 1),
        "normalized": round(float(normalized or 0), 8),
    }


def compute_pathogen_trend(history: list[dict[str, Any]]) -> str:
    """Classify a 21-day pathogen history as rising, stable, or falling."""
    if len(history) < 2:
        return "stable"

    first = history[0]
    last = history[-1]
    rank_delta = int(last.get("activity_rank", -1)) - int(first.get("activity_rank", -1))

    first_norm = float(first.get("normalized") or 0)
    last_norm = float(last.get("normalized") or 0)
    norm_ratio = (last_norm / first_norm) if first_norm > 0 else None

    if rank_delta >= 2:
        return "rising"
    if rank_delta <= -2:
        return "falling"
    if rank_delta == 1 and last.get("alert"):
        return "rising"
    if rank_delta == -1 and first.get("alert") and not last.get("alert"):
        return "falling"
    if norm_ratio is not None:
        if norm_ratio >= 1.75 and last.get("alert"):
            return "rising"
        if norm_ratio <= 0.55 and not last.get("alert"):
            return "falling"
    return "stable"


def parse_plant_series(
    samples: list[dict[str, Any]],
    target_display: dict[str, str],
    *,
    window_days: int = TREND_WINDOW_DAYS,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Parse a plant time series into latest pathogen levels plus per-pathogen trends."""
    if not samples:
        return None

    latest = samples[-1]
    collection_date = str(latest.get("collection_date") or "")
    sample_dt = _parse_collection_date(collection_date)
    if sample_dt and sample_dt < _utcnow() - timedelta(days=max_age_days):
        return None

    cutoff = _utcnow() - timedelta(days=window_days)
    window_samples: list[dict[str, Any]] = []
    for sample in samples:
        sample_date = _parse_collection_date(sample.get("collection_date"))
        if sample_date and sample_date < cutoff:
            continue
        window_samples.append(sample)
    if not window_samples:
        window_samples = [latest]

    history_by_target: dict[str, list[dict[str, Any]]] = {
        key: [] for key in target_display
    }

    for sample in window_samples:
        sample_date = str(sample.get("collection_date") or "")
        targets = sample.get("targets") or {}
        for target_key in target_display:
            target_data = targets.get(target_key)
            if not isinstance(target_data, dict):
                continue
            point = extract_pathogen_point(target_data)
            if not point:
                continue
            history_by_target[target_key].append(
                {
                    "date": sample_date,
                    **point,
                }
            )

    pathogens: list[dict[str, Any]] = []
    alert_count = 0
    for target_key, display_name in target_display.items():
        history = history_by_target.get(target_key) or []
        if not history:
            continue
        latest_point = history[-1]
        trend = compute_pathogen_trend(history)
        if latest_point.get("alert"):
            alert_count += 1
        pathogens.append(
            {
                "name": display_name,
                "target_key": target_key,
                "concentration": latest_point.get("concentration", 0),
                "normalized": latest_point.get("normalized", 0),
                "activity": latest_point.get("activity", "not calculated"),
                "alert": bool(latest_point.get("alert")),
                "trend": trend,
                "history": history[-8:],
            }
        )

    if not pathogens:
        return None

    sample_age_days = None
    if sample_dt:
        sample_age_days = max(0, (_utcnow() - sample_dt).days)

    return {
        "collection_date": collection_date,
        "sample_age_days": sample_age_days,
        "pathogens": pathogens,
        "alert_count": alert_count,
    }


def build_pathogen_rollups(plants: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate per-pathogen site/state counts and rising signals."""
    rollups: dict[str, dict[str, Any]] = {}

    for plant in plants:
        state = str(plant.get("state") or "").strip()
        if not state:
            continue
        for pathogen in plant.get("pathogens") or []:
            name = str(pathogen.get("name") or "").strip()
            if not name:
                continue
            bucket = rollups.setdefault(
                name,
                {
                    "name": name,
                    "target_key": pathogen.get("target_key"),
                    "sites_total": 0,
                    "sites_alert": 0,
                    "sites_rising": 0,
                    "states_alert": set(),
                    "states_rising": set(),
                },
            )
            bucket["sites_total"] += 1
            if pathogen.get("alert"):
                bucket["sites_alert"] += 1
                bucket["states_alert"].add(state)
            if pathogen.get("trend") == "rising":
                bucket["sites_rising"] += 1
                bucket["states_rising"].add(state)

    for bucket in rollups.values():
        bucket["states_alert"] = sorted(bucket["states_alert"])
        bucket["states_rising"] = sorted(bucket["states_rising"])
        bucket["states_alert_count"] = len(bucket["states_alert"])
        bucket["states_rising_count"] = len(bucket["states_rising"])
    return rollups


def _compact_snapshot(rollups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "states_alert_count": data.get("states_alert_count", 0),
            "states_rising_count": data.get("states_rising_count", 0),
            "sites_alert": data.get("sites_alert", 0),
            "sites_rising": data.get("sites_rising", 0),
        }
        for name, data in rollups.items()
    }


def save_daily_snapshot(rollups: dict[str, dict[str, Any]], *, now: datetime | None = None) -> str:
    """Persist a compact daily national rollup for week-over-week comparisons."""
    day = (now or _utcnow()).strftime("%Y-%m-%d")
    directory = _snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{day}.json"
    payload = {
        "date": day,
        "captured_at": (now or _utcnow()).isoformat(),
        "pathogens": _compact_snapshot(rollups),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _prune_old_snapshots(directory)
    return day


def _prune_old_snapshots(directory: Path) -> None:
    cutoff = _utcnow() - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    for path in directory.glob("*.json"):
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink()
            except OSError:
                logger.debug("Failed to prune wastewater snapshot %s", path)


def load_baseline_snapshot(*, lookback_days: int = BASELINE_LOOKBACK_DAYS) -> dict[str, Any] | None:
    directory = _snapshot_dir()
    if not directory.exists():
        return None
    target_day = (_utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    exact = directory / f"{target_day}.json"
    if exact.exists():
        try:
            return json.loads(exact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    candidates: list[tuple[str, Path]] = []
    for path in directory.glob("*.json"):
        if path.stem <= target_day:
            candidates.append((path.stem, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    try:
        return json.loads(candidates[0][1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _rate_increase(current: int, baseline: int) -> float | None:
    if baseline <= 0:
        return None
    return round(((current - baseline) / baseline) * 100.0, 1)


def _rate_display(current: int, baseline: int, delta: int) -> str:
    if baseline <= 0:
        if current <= 0:
            return "n/a"
        if delta > 0:
            return f"+{delta} states (new)"
        return f"{current} states (new)"
    rate = _rate_increase(current, baseline)
    if rate is None:
        return "n/a"
    sign = "+" if rate > 0 else ""
    return f"{sign}{rate}%"


def build_surveillance_summary(
    plants: list[dict[str, Any]],
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build national biosurveillance rollup for the map beacon."""
    active_plants = [plant for plant in plants if plant.get("pathogens")]
    rollups = build_pathogen_rollups(active_plants)
    baseline_pathogens = (baseline or {}).get("pathogens") or {}

    pathogen_rows: list[dict[str, Any]] = []
    for name, bucket in rollups.items():
        base = baseline_pathogens.get(name) or {}
        rising_states = int(bucket.get("states_rising_count") or 0)
        alert_states = int(bucket.get("states_alert_count") or 0)
        base_rising = int(base.get("states_rising_count") or 0)
        base_alert = int(base.get("states_alert_count") or 0)
        rising_delta = rising_states - base_rising
        row = {
            "name": name,
            "target_key": bucket.get("target_key"),
            "states_rising": rising_states,
            "states_alert": alert_states,
            "sites_rising": int(bucket.get("sites_rising") or 0),
            "sites_alert": int(bucket.get("sites_alert") or 0),
            "states_rising_delta": rising_delta,
            "states_alert_delta": alert_states - base_alert,
            "rising_rate_pct": _rate_increase(rising_states, base_rising),
            "rising_rate_display": _rate_display(rising_states, base_rising, rising_delta),
            "alert_rate_pct": _rate_increase(alert_states, base_alert),
            "trend": "rising"
            if rising_states > 0
            else "stable",
        }
        pathogen_rows.append(row)

    pathogen_rows.sort(
        key=lambda row: (
            int(row.get("states_rising") or 0),
            float(row.get("rising_rate_pct") or 0),
            int(row.get("states_alert") or 0),
        ),
        reverse=True,
    )
    rising_rows = [row for row in pathogen_rows if int(row.get("states_rising") or 0) > 0]

    return {
        "updated_at": _utcnow().isoformat(),
        "baseline_date": baseline.get("date") if baseline else None,
        "baseline_lookback_days": BASELINE_LOOKBACK_DAYS,
        "marker": {"lat": US_SURVEILLANCE_LAT, "lng": US_SURVEILLANCE_LNG},
        "plants_monitored": len(plants),
        "plants_active": len(active_plants),
        "pathogens_tracked": len(pathogen_rows),
        "pathogens_rising": len(rising_rows),
        "pathogens": pathogen_rows,
        "rising_pathogens": rising_rows,
        "signature": "|".join(
            f"{row['name']}:{row['states_rising']}:{row.get('rising_rate_display')}"
            for row in rising_rows[:12]
        ),
    }