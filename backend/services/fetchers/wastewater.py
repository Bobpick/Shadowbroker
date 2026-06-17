"""WastewaterSCAN fetcher — pathogen surveillance via wastewater monitoring.

Data source: Stanford/Emory WastewaterSCAN project
  - Plant locations: https://storage.googleapis.com/wastewater-dev-data/json/plants.json
  - Time series:     https://storage.googleapis.com/wastewater-dev-data/json/{uuid}.json

Series loads are spread across rotating batches so startup and slow-tier
jobs stay within fetch timeouts while coverage climbs toward all plants.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, latest_data
from services.fetchers.wastewater_trends import (
    build_pathogen_rollups,
    build_surveillance_summary,
    load_baseline_snapshot,
    parse_plant_series,
    save_daily_snapshot,
    _snapshot_dir,
)
from services.network_utils import UpstreamCircuitBreakerError, fetch_with_curl

logger = logging.getLogger(__name__)

_GCS_BASE = "https://storage.googleapis.com/wastewater-dev-data/json"

_BATCH_SIZE = int(os.environ.get("WASTEWATER_BATCH_SIZE", "36"))
_BATCH_TIMEOUT_S = float(os.environ.get("WASTEWATER_BATCH_TIMEOUT_S", "70"))
_PLANT_FETCH_TIMEOUT_S = int(os.environ.get("WASTEWATER_PLANT_TIMEOUT_S", "10"))
_BATCH_WORKERS = int(os.environ.get("WASTEWATER_BATCH_WORKERS", "8"))

# Cache the plants list for 24 hours (it rarely changes)
_plants_cache: list[dict] = []
_plants_cache_ts: float = 0
_PLANTS_CACHE_TTL = 86400  # 24 hours
_PLANTS_TIMEOUT_S = int(os.environ.get("WASTEWATER_PLANTS_TIMEOUT_S", "60"))


def _plants_disk_cache_path() -> Path:
    raw = os.environ.get("WASTEWATER_PLANTS_CACHE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "wastewater_plants_cache.json"


def _plants_seed_path() -> Path:
    return Path(__file__).resolve().parent / "wastewater_plants_seed.json"


def _load_plants_payload(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        plants = payload.get("plants") if isinstance(payload, dict) else payload
        if isinstance(plants, list):
            return [p for p in plants if isinstance(p, dict)]
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("WastewaterSCAN: could not read plants from %s: %s", path, exc)
    return []


def _save_plants_disk_cache(plants: list[dict]) -> None:
    if not plants:
        return
    path = _plants_disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"plants": plants}), encoding="utf-8")
    except OSError as exc:
        logger.debug("WastewaterSCAN: could not write plants cache to %s: %s", path, exc)


def _fallback_plants() -> list[dict]:
    for path in (_plants_disk_cache_path(), _plants_seed_path()):
        plants = _load_plants_payload(path)
        if plants:
            logger.info("WastewaterSCAN: using %s plant locations from %s", len(plants), path.name)
            return plants
    return []

# Friendly display labels for known targets — unknown targets use their raw key.
_TARGET_DISPLAY: dict[str, str] = {
    "N Gene": "COVID-19",
    "Influenza A F1R1": "Influenza A",
    "Influenza B": "Influenza B",
    "RSV": "RSV",
    "Noro_G2": "Norovirus",
    "MPXV_G2R_WA": "Mpox",
    "InfA_H5": "H5N1 (Bird Flu)",
    "HMPV_4": "HMPV",
    "Rota": "Rotavirus",
    "HAV": "Hepatitis A",
    "C_auris": "Candida auris",
    "EVD68": "Enterovirus D68",
}


def _fetch_state_path() -> Path:
    raw = os.environ.get("WASTEWATER_FETCH_STATE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "wastewater_fetch_state.json"


def _load_fetch_state() -> dict[str, Any]:
    path = _fetch_state_path()
    if not path.exists():
        return {"cursor": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        logger.debug("WastewaterSCAN: could not read fetch state from %s", path)
    return {"cursor": 0}


def _save_fetch_state(state: dict[str, Any]) -> None:
    path = _fetch_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def select_batch_ids(
    all_ids: list[str],
    plant_map: dict[str, dict[str, Any]],
    *,
    cursor: int,
    batch_size: int,
) -> tuple[list[str], int]:
    """Pick the next plant IDs to fetch, prioritizing sites without series data."""
    ordered = sorted(all_ids)
    if not ordered:
        return [], 0

    unfetched = [
        pid
        for pid in ordered
        if not (plant_map.get(pid) or {}).get("pathogens")
    ]
    batch: list[str] = unfetched[:batch_size]

    if len(batch) < batch_size:
        index = cursor % len(ordered)
        guard = 0
        while len(batch) < batch_size and guard < len(ordered) * 2:
            pid = ordered[index % len(ordered)]
            if pid not in batch:
                batch.append(pid)
            index += 1
            guard += 1
        cursor = index % len(ordered)

    return batch, cursor


def _snapshot_exists_today() -> bool:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (_snapshot_dir() / f"{day}.json").exists()


def _fetch_plants() -> list[dict]:
    """Fetch the full plants list from GCS, with 24h caching."""
    global _plants_cache, _plants_cache_ts

    if _plants_cache and (time.time() - _plants_cache_ts) < _PLANTS_CACHE_TTL:
        return _plants_cache

    url = f"{_GCS_BASE}/plants.json"
    try:
        resp = fetch_with_curl(url, timeout=_PLANTS_TIMEOUT_S)
    except (UpstreamCircuitBreakerError, Exception) as exc:
        logger.warning("WastewaterSCAN plants fetch error: %s", exc)
        if _plants_cache:
            return _plants_cache
        return _fallback_plants()

    if resp.status_code != 200:
        logger.warning("WastewaterSCAN plants fetch failed: HTTP %s", resp.status_code)
        if _plants_cache:
            return _plants_cache
        return _fallback_plants()

    data = resp.json()
    plants = data.get("plants", [])
    if not plants:
        if _plants_cache:
            return _plants_cache
        return _fallback_plants()

    _plants_cache = plants
    _plants_cache_ts = time.time()
    _save_plants_disk_cache(plants)
    logger.info("WastewaterSCAN: cached %s plant locations", len(plants))
    return plants


def _blank_plant_record(p: dict[str, Any], pid: str, coords: list[float]) -> dict[str, Any]:
    return {
        "id": pid,
        "name": p.get("name", ""),
        "site_name": p.get("site_name", ""),
        "city": p.get("city", ""),
        "state": p.get("state", ""),
        "country": p.get("country", "US"),
        "population": p.get("sewershed_pop"),
        "lat": coords[1],
        "lng": coords[0],
        "pathogens": [],
        "alert_count": 0,
        "collection_date": "",
        "sample_age_days": None,
        "source": "WastewaterSCAN",
    }


def _build_plant_map(plants: list[dict]) -> dict[str, dict[str, Any]]:
    plant_map: dict[str, dict[str, Any]] = {}
    for p in plants:
        point = p.get("point") or {}
        coords = point.get("coordinates") or []
        if len(coords) < 2:
            continue
        pid = p.get("id") or p.get("uuid", "")
        if not pid:
            continue
        plant_map[pid] = _blank_plant_record(p, pid, coords)
    return plant_map


def _merge_cached_pathogens(plant_map: dict[str, dict[str, Any]]) -> None:
    with _data_lock:
        cached_nodes = latest_data.get("wastewater") or []
    for node in cached_nodes:
        pid = str(node.get("id") or "")
        if not pid or pid not in plant_map:
            continue
        if not node.get("pathogens"):
            continue
        plant_map[pid]["pathogens"] = node.get("pathogens") or []
        plant_map[pid]["alert_count"] = int(node.get("alert_count") or 0)
        plant_map[pid]["collection_date"] = node.get("collection_date") or ""
        plant_map[pid]["sample_age_days"] = node.get("sample_age_days")


def _fetch_plant_series(plant_id: str) -> dict[str, Any] | None:
    url = f"{_GCS_BASE}/{plant_id}.json"
    try:
        resp = fetch_with_curl(url, timeout=_PLANT_FETCH_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        samples = resp.json().get("samples", [])
        return parse_plant_series(samples, _TARGET_DISPLAY)
    except Exception as exc:
        logger.debug("WastewaterSCAN: failed to fetch plant %s: %s", plant_id, exc)
        return None


def _fetch_plant_batch(batch_ids: list[str], plant_map: dict[str, dict[str, Any]]) -> int:
    if not batch_ids:
        return 0

    success_count = 0
    pending: set[concurrent.futures.Future] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=_BATCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_plant_series, pid): pid for pid in batch_ids}
        pending = set(futures.keys())
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=_BATCH_TIMEOUT_S):
                pending.discard(fut)
                pid = futures[fut]
                try:
                    result = fut.result()
                    if not result:
                        continue
                    plant_map[pid]["pathogens"] = result["pathogens"]
                    plant_map[pid]["alert_count"] = result["alert_count"]
                    plant_map[pid]["collection_date"] = result["collection_date"]
                    plant_map[pid]["sample_age_days"] = result.get("sample_age_days")
                    success_count += 1
                except Exception:
                    pass
        except TimeoutError:
            logger.warning(
                "WastewaterSCAN batch: %s/%s plant series still pending — keeping partial results",
                len(pending),
                len(futures),
            )
            for fut in pending:
                fut.cancel()
    return success_count


def fetch_wastewater():
    """Fetch one rotating WastewaterSCAN batch and merge into cached plant data."""
    from services.fetchers._store import is_any_active

    if not is_any_active("wastewater"):
        return

    plants = _fetch_plants()
    if not plants:
        logger.warning("WastewaterSCAN: no plant data available")
        return

    plant_map = _build_plant_map(plants)
    _merge_cached_pathogens(plant_map)

    all_ids = sorted(plant_map.keys())
    state = _load_fetch_state()
    cursor = int(state.get("cursor") or 0)
    batch_ids, new_cursor = select_batch_ids(
        all_ids,
        plant_map,
        cursor=cursor,
        batch_size=_BATCH_SIZE,
    )

    batch_ok = _fetch_plant_batch(batch_ids, plant_map)

    state.update(
        {
            "cursor": new_cursor,
            "last_batch_at": datetime.now(timezone.utc).isoformat(),
            "last_batch_ids": len(batch_ids),
            "last_batch_ok": batch_ok,
        }
    )
    _save_fetch_state(state)

    nodes = list(plant_map.values())
    active_nodes = [n for n in nodes if n.get("pathogens")]

    if active_nodes and not _snapshot_exists_today():
        rollups = build_pathogen_rollups(active_nodes)
        save_daily_snapshot(rollups)

    baseline = load_baseline_snapshot()
    surveillance = build_surveillance_summary(nodes, baseline=baseline)
    surveillance["fetch_progress"] = {
        "with_data": len(active_nodes),
        "total": len(nodes),
        "batch_fetched": batch_ok,
        "batch_size": len(batch_ids),
        "cursor": new_cursor,
    }

    logger.info(
        "WastewaterSCAN batch: fetched %s/%s plants (%s/%s total with data), %s rising pathogens",
        batch_ok,
        len(batch_ids),
        len(active_nodes),
        len(nodes),
        surveillance.get("pathogens_rising", 0),
    )

    with _data_lock:
        latest_data["wastewater"] = nodes
        latest_data["wastewater_surveillance"] = surveillance
    if nodes:
        _mark_fresh("wastewater")