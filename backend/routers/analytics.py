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
from analytics.gt_alerts import top_gt_alerts
from analytics.us_cities import build_us_city_watch
from analytics.micro_rolling import micro_rolling_report
from analytics.rolling_backtest import (
    auto_label_mature_weeks,
    freeze_weekly_snapshot,
    label_region,
    label_regions,
    rolling_alert_threshold,
    rolling_report,
    score_week,
)
from analytics.weekly_store import load_week
from analytics.settings import gt_analytics_enabled
from analytics.nash_deterrence import (
    build_strategic_analysis,
    delete_flashpoint,
    get_flashpoint,
    list_flashpoints,
    nash_deterrence_enabled,
    record_entity_hint,
    reset_presets,
    upsert_flashpoint,
)
from analytics.delta_report import (
    delta_report_enabled,
    generate_delta_report,
    get_last_report_meta,
    list_recent_reports,
)
from services.fetchers._store import _data_lock, get_latest_data_subset_refs, latest_data

logger = logging.getLogger(__name__)

router = APIRouter()


class RiskHeatmapRequest(BaseModel):
    """Optional batch ingest + refresh controls for POST /api/analytics/risk_heatmap."""

    refresh: bool = True
    items: list[dict[str, Any]] = Field(default_factory=list)


class RollingFreezeRequest(BaseModel):
    week_id: str | None = None
    force: bool = False


class RollingLabelEntry(BaseModel):
    region: str
    label: str
    notes: str = ""


class RollingLabelRequest(BaseModel):
    week_id: str
    labels: list[RollingLabelEntry] = Field(default_factory=list)


class RollingAutoLabelRequest(BaseModel):
    label_delay_days: int | None = None
    force_now: bool = False


class FlashpointUpsertRequest(BaseModel):
    id: str | None = None
    label: str | None = None
    lat: float | None = None
    lng: float | None = None
    row_actor: str | None = None
    col_actor: str | None = None
    row_strategies: list[str] | None = None
    col_strategies: list[str] | None = None
    payoffs: list[list[list[float]]] | None = None
    gt_regions: list[str] | None = None
    keywords: list[str] | None = None
    current_row: int | None = None
    current_col: int | None = None
    locked_strategies: bool | None = None


class EntityHintRequest(BaseModel):
    entity_type: str = ""
    entity_id: str = ""
    label: str = ""
    lat: float
    lng: float
    flashpoint_id: str = ""


class DeltaReportRequest(BaseModel):
    force: bool = False
    preview: bool = False


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


@router.get("/api/analytics/rolling")
@limiter.limit("12/minute")
async def analytics_rolling(
    request: Request,
    weeks: int = 8,
    target_confidence: float = 0.80,
) -> dict[str, Any]:
    """Rolling weekly operational validation — accuracy trend with delayed labels."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = rolling_report(weeks=max(1, min(weeks, 52)), target_confidence=target_confidence)
    report["enabled"] = True
    return report


@router.get("/api/analytics/us_cities")
@limiter.limit("30/minute")
async def analytics_us_cities(
    request: Request,
    limit: int = 20,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """US metro protest watch — city-level unrest from Telegram/Reddit + GT."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    with _data_lock:
        gt_snap = dict(latest_data.get("gt_risk") or {})
        telegram_snap = dict(latest_data.get("telegram_osint") or {})
        reddit_snap = dict(latest_data.get("reddit_osint") or {})

    cached = gt_snap.get("us_cities")
    if isinstance(cached, dict) and cached.get("cities"):
        payload = dict(cached)
        payload["enabled"] = True
        payload["cities"] = list(payload.get("cities") or [])[: max(1, min(limit, 20))]
        return payload

    report = build_us_city_watch(
        gt_risk=gt_snap,
        telegram_osint=telegram_snap,
        reddit_osint=reddit_snap,
        lookback_days=max(1, min(lookback_days, 30)),
        limit=max(1, min(limit, 20)),
    )
    report["enabled"] = True
    return report


@router.get("/api/analytics/alerts")
@limiter.limit("30/minute")
async def analytics_top_alerts(
    request: Request,
    limit: int = 8,
) -> dict[str, Any]:
    """Top GT risk regions ranked by score — fly-to targets for the map."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = top_gt_alerts(limit=max(1, min(limit, 25)))
    report["enabled"] = True
    return report


@router.get("/api/analytics/rolling/micro")
@limiter.limit("30/minute")
async def analytics_rolling_micro(
    request: Request,
    window_days: int = 3,
    limit: int = 15,
) -> dict[str, Any]:
    """Rolling 3-day micro average — spot vs baseline, ignition detection."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = micro_rolling_report(
        window_days=max(2, min(window_days, 7)),
        limit=max(1, min(limit, 50)),
    )
    report["enabled"] = True
    return report


@router.get("/api/analytics/rolling/{week_id}")
@limiter.limit("12/minute")
async def analytics_rolling_week(request: Request, week_id: str) -> dict[str, Any]:
    """Return a single frozen week snapshot and its score."""
    if not gt_analytics_enabled():
        return {"enabled": False, "message": "Strategic Risk Analytics is disabled."}

    snapshot = load_week(str(week_id).strip())
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Week {week_id} not found")

    score = score_week(snapshot)
    return {
        "enabled": True,
        "week_id": snapshot.week_id,
        "snapshot": snapshot.to_dict(),
        "score": score.to_dict(),
        "alert_threshold": rolling_alert_threshold(),
    }


@router.post("/api/analytics/rolling/freeze")
@limiter.limit("6/minute")
async def analytics_rolling_freeze(
    request: Request,
    body: RollingFreezeRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """Freeze current GT scores for the ISO week (idempotent unless force=true)."""
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    result = freeze_weekly_snapshot(
        week_id=body.week_id,
        force=body.force,
        frozen_by="api",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("detail", "Freeze failed"))
    result["enabled"] = True
    return result


@router.post("/api/analytics/rolling/auto-label")
@limiter.limit("6/minute")
async def analytics_rolling_auto_label(
    request: Request,
    body: RollingAutoLabelRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """Infer delayed outcome labels for mature frozen weeks (operator trigger)."""
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    delay_days = 0 if body.force_now else body.label_delay_days
    result = auto_label_mature_weeks(
        label_delay_days=delay_days,
        labeled_by="api",
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=503,
            detail=result.get("detail", "Auto-label failed"),
        )
    report = rolling_report(weeks=8)
    result["enabled"] = True
    result["rolling"] = report
    return result


@router.post("/api/analytics/rolling/label")
@limiter.limit("12/minute")
async def analytics_rolling_label(
    request: Request,
    body: RollingLabelRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """Apply delayed outcome labels to a frozen week."""
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    week_id = str(body.week_id or "").strip()
    if not week_id:
        raise HTTPException(status_code=400, detail="week_id required")

    if len(body.labels) == 1:
        entry = body.labels[0]
        result = label_region(
            week_id,
            entry.region,
            entry.label,  # type: ignore[arg-type]
            notes=entry.notes,
            labeled_by="api",
        )
    else:
        result = label_regions(
            week_id,
            [row.model_dump() for row in body.labels],
            labeled_by="api",
        )

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("detail", "Label failed"))
    result["enabled"] = True
    return result


# ── Nash / Deterrence (Strategic Analysis) ──────────────────────────────────


@router.get("/api/analytics/strategic")
@limiter.limit("30/minute")
async def strategic_analysis_get(request: Request) -> dict[str, Any]:
    """Nash / deterrence snapshot for all flashpoints."""
    if not nash_deterrence_enabled():
        return {
            "enabled": False,
            "flashpoints": [],
            "message": "Nash / Deterrence is disabled (NASH_DETERRENCE_ENABLED).",
        }
    with _data_lock:
        gt_snap = dict(latest_data.get("gt_risk") or {})
        telegram_snap = dict(latest_data.get("telegram_osint") or {})
        reddit_snap = dict(latest_data.get("reddit_osint") or {})
    return build_strategic_analysis(
        gt_risk=gt_snap,
        telegram=telegram_snap,
        reddit=reddit_snap,
    )


@router.get("/api/analytics/strategic/flashpoints")
@limiter.limit("30/minute")
async def strategic_flashpoints_list(request: Request) -> dict[str, Any]:
    if not nash_deterrence_enabled():
        return {"enabled": False, "flashpoints": []}
    return {"enabled": True, "flashpoints": list_flashpoints()}


@router.get("/api/analytics/strategic/flashpoints/{fp_id}")
@limiter.limit("30/minute")
async def strategic_flashpoint_get(request: Request, fp_id: str) -> dict[str, Any]:
    if not nash_deterrence_enabled():
        raise HTTPException(status_code=503, detail="Nash / Deterrence disabled")
    fp = get_flashpoint(fp_id)
    if not fp:
        raise HTTPException(status_code=404, detail="Flashpoint not found")
    with _data_lock:
        gt_snap = dict(latest_data.get("gt_risk") or {})
        telegram_snap = dict(latest_data.get("telegram_osint") or {})
        reddit_snap = dict(latest_data.get("reddit_osint") or {})
    from analytics.nash_deterrence import analyze_flashpoint

    return {
        "enabled": True,
        "flashpoint": analyze_flashpoint(
            fp, gt_risk=gt_snap, telegram=telegram_snap, reddit=reddit_snap
        ),
    }


@router.post("/api/analytics/strategic/flashpoints", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def strategic_flashpoint_upsert(
    request: Request,
    body: FlashpointUpsertRequest,
) -> dict[str, Any]:
    if not nash_deterrence_enabled():
        raise HTTPException(status_code=503, detail="Nash / Deterrence disabled")
    fp = upsert_flashpoint(body.model_dump(exclude_none=True))
    return {"ok": True, "flashpoint": fp}


@router.delete(
    "/api/analytics/strategic/flashpoints/{fp_id}",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("20/minute")
async def strategic_flashpoint_delete(request: Request, fp_id: str) -> dict[str, Any]:
    if not nash_deterrence_enabled():
        raise HTTPException(status_code=503, detail="Nash / Deterrence disabled")
    ok = delete_flashpoint(fp_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Flashpoint not found")
    return {"ok": True}


@router.post(
    "/api/analytics/strategic/reset-presets",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("5/minute")
async def strategic_reset_presets(request: Request) -> dict[str, Any]:
    if not nash_deterrence_enabled():
        raise HTTPException(status_code=503, detail="Nash / Deterrence disabled")
    return {"ok": True, "flashpoints": reset_presets()}


@router.post(
    "/api/analytics/strategic/entity-hint",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("30/minute")
async def strategic_entity_hint(request: Request, body: EntityHintRequest) -> dict[str, Any]:
    """Attach a map entity click to the nearest (or specified) flashpoint."""
    if not nash_deterrence_enabled():
        raise HTTPException(status_code=503, detail="Nash / Deterrence disabled")
    hint = record_entity_hint(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        label=body.label,
        lat=body.lat,
        lng=body.lng,
        flashpoint_id=body.flashpoint_id,
    )
    return {"ok": True, "hint": hint}


# ── Delta reports ───────────────────────────────────────────────────────────


@router.get("/api/analytics/delta-report")
@limiter.limit("20/minute")
async def delta_report_status(request: Request) -> dict[str, Any]:
    return {
        "enabled": delta_report_enabled(),
        "last": get_last_report_meta(),
        "history": list_recent_reports(10),
        "view_url": "/api/analytics/delta-report/view",
    }


@router.get("/api/analytics/delta-report/view")
@limiter.limit("60/minute")
async def delta_report_view(request: Request):
    """
    Serve the latest SITREP HTML over HTTP.

    Prefer this over file:// — Snap Firefox often blocks local files written
    by the Docker backend (uid 1001) even when world-readable.
    """
    from fastapi.responses import FileResponse, HTMLResponse

    from analytics.delta_report import latest_report_html_path

    path = latest_report_html_path()
    if path is None:
        # Auto-generate once if missing
        if delta_report_enabled() or True:
            with _data_lock:
                gt_snap = dict(latest_data.get("gt_risk") or {})
            generate_delta_report(force=True, preview=False, gt_risk=gt_snap)
            path = latest_report_html_path()
    if path is None:
        return HTMLResponse(
            "<html><body style='background:#0b1220;color:#e2e8f0;font-family:monospace;padding:2rem'>"
            "<h1>No SITREP yet</h1><p>Enable GT analytics and POST /api/analytics/delta-report "
            "with {\"force\":true}, or wait for the 6-hour scheduler.</p></body></html>",
            status_code=404,
        )
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename="Shadowbroker_Strategic_Delta.html",
        headers={"Cache-Control": "no-cache"},
    )


@router.post(
    "/api/analytics/delta-report",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("10/minute")
async def delta_report_generate(
    request: Request,
    body: DeltaReportRequest,
) -> dict[str, Any]:
    """Generate (or preview) a strategic delta report now."""
    if not delta_report_enabled() and not body.force and not body.preview:
        raise HTTPException(status_code=503, detail="Delta reports disabled")
    with _data_lock:
        gt_snap = dict(latest_data.get("gt_risk") or {})
    return generate_delta_report(
        force=body.force or body.preview,
        preview=body.preview,
        gt_risk=gt_snap,
    )