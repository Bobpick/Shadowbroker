"""Strategic Risk Analytics API — game-theoretic early warning overlays."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from analytics.backtest import (
    DEFAULT_BACKTEST_ALERT_THRESHOLD,
    run_historical_backtest,
    tune_alert_threshold,
)
from analytics.feed_adapter import normalize_feed_item
from analytics.integration import get_gt_engine, refresh_from_latest_data
from analytics.settings import gt_analytics_enabled
from services.fetchers._store import _data_lock, get_latest_data_subset_refs, latest_data

logger = logging.getLogger(__name__)

router = APIRouter()


class RiskHeatmapRequest(BaseModel):
    """Optional batch ingest + refresh controls for POST /api/analytics/risk_heatmap."""

    refresh: bool = True
    items: list[dict[str, Any]] = Field(default_factory=list)


def _empty_heatmap() -> dict[str, Any]:
    return {
        "enabled": False,
        "type": "FeatureCollection",
        "features": [],
        "clusters": [],
        "processed": 0,
        "timestamp": None,
    }


def _gt_risk_payload() -> dict[str, Any]:
    snap = get_latest_data_subset_refs("gt_risk")
    payload = snap.get("gt_risk")
    if not isinstance(payload, dict):
        return _empty_heatmap()
    heatmap = payload.get("heatmap") or {"type": "FeatureCollection", "features": []}
    return {
        "enabled": bool(payload.get("enabled")),
        "type": heatmap.get("type", "FeatureCollection"),
        "features": list(heatmap.get("features") or []),
        "clusters": list(payload.get("clusters") or []),
        "processed": int(payload.get("processed") or 0),
        "timestamp": payload.get("timestamp"),
    }


@router.get("/api/analytics/risk_heatmap")
@limiter.limit("60/minute")
async def risk_heatmap_get(request: Request) -> dict[str, Any]:
    """Return cached GeoJSON risk overlay (posterior scores per region)."""
    if not gt_analytics_enabled():
        return _empty_heatmap()
    return _gt_risk_payload()


@router.post("/api/analytics/risk_heatmap")
@limiter.limit("12/minute")
async def risk_heatmap_post(
    request: Request,
    body: RiskHeatmapRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """
    Ingest optional feed items and/or refresh beliefs from latest intel layers.

    Requires local operator auth — intended for OpenClaw agents and admin tooling.
    """
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    engine = get_gt_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics engine unavailable")

    ingested = 0
    for raw in body.items:
        if not isinstance(raw, dict):
            continue
        source_type = str(raw.get("source_type") or "manual")
        item = normalize_feed_item(raw, source_type=source_type)
        result = engine.process_feed_item(item)
        if result and not result.get("skipped"):
            ingested += 1

    summary: dict[str, Any] = {"ingested": ingested}
    if body.refresh:
        with _data_lock:
            snapshot = dict(latest_data)
        summary.update(refresh_from_latest_data(snapshot, persist=True))

    payload = _gt_risk_payload()
    payload["ingested"] = ingested
    payload["refresh"] = bool(body.refresh)
    return payload


@router.get("/api/analytics/dossier/{region}")
@limiter.limit("30/minute")
async def analytics_dossier(request: Request, region: str) -> dict[str, Any]:
    """Game-theoretic rationale, recent costly signals, and scenario sketches."""
    region_key = str(region or "").strip().lower()
    if not region_key or len(region_key) > 120:
        raise HTTPException(status_code=400, detail="Invalid region identifier")

    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "region": region_key,
            "current_risk": 0.0,
            "interpretation": "Strategic Risk Analytics is disabled.",
            "recent_signals": [],
            "scenarios": [],
        }

    engine = get_gt_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics engine unavailable")

    dossier = engine.get_dossier(region_key)
    dossier["enabled"] = True
    return dossier


@router.get("/api/analytics/backtest")
@limiter.limit("6/minute")
async def analytics_backtest(
    request: Request,
    expanded: bool = True,
    tune: bool = False,
    target_confidence: float = 0.95,
) -> dict[str, Any]:
    """
    Run labeled historical backtest and return accuracy + Wilson 95% CI.

    ``confidence_rate`` is the Wilson lower bound (conservative pass metric).
    """
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    if tune:
        threshold, report = tune_alert_threshold(target_confidence=target_confidence)
    else:
        threshold = DEFAULT_BACKTEST_ALERT_THRESHOLD
        report = run_historical_backtest(
            use_expanded_suite=expanded,
            alert_threshold=threshold,
            target_confidence=target_confidence,
        )

    payload = report.to_dict()
    payload["enabled"] = True
    payload["expanded_suite"] = expanded
    payload["tuned"] = tune
    payload["recommended_alert_threshold"] = threshold
    return payload