"""Automated strategic delta reports — decision-support briefing format.

Answers in ~15 seconds:
  1. What changed?
  2. Why does it matter?
  3. What should I watch next?

Markdown + HTML (optional PDF). Delivery: local files, SMTP, webhook.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_run_iso: str | None = None
_last_report_meta: dict[str, Any] | None = None

_DATA_DIR = Path(os.path.dirname(os.path.dirname(__file__))) / "data"
_REPORT_DIR = _DATA_DIR / "delta_reports"
_STATE_FILE = _DATA_DIR / "delta_report_state.json"

# Flashpoint id → coarse theater for regional heat
_THEATER_MAP: dict[str, str] = {
    "taiwan_strait": "Indo-Pacific",
    "south_china_sea": "Indo-Pacific",
    "korean_peninsula": "Indo-Pacific",
    "ukraine_borders": "Europe",
    "baltic_nato": "Europe",
    "strait_of_hormuz": "Middle East",
}

_HR = "──────────────────────────────────────────────────────────────"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, "")).strip() or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except ValueError:
        return default


def delta_report_enabled() -> bool:
    raw = str(os.environ.get("DELTA_REPORT_ENABLED", "")).strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off"}
    try:
        from analytics.settings import gt_analytics_enabled

        return gt_analytics_enabled()
    except Exception:
        return False


def delta_report_interval_hours() -> int:
    return max(1, _env_int("DELTA_REPORT_INTERVAL_HOURS", 6))


def delta_threshold() -> float:
    return max(0.01, _env_float("DELTA_REPORT_GT_THRESHOLD", 0.08))


def _load_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("delta_report state save failed: %s", exc)


# ── Severity / presentation helpers ─────────────────────────────────────────


def alert_level(det_score: float, nash_score: float, nash_band: str = "") -> str:
    """Military-style GREEN → BLACK from deterrence + Nash."""
    band = str(nash_band or "").lower()
    if det_score < 20 or (band == "unstable" and det_score < 30):
        return "BLACK"
    if det_score < 35 or band == "unstable":
        return "RED"
    if det_score < 50 or band == "watch":
        return "ORANGE"
    if det_score < 70:
        return "YELLOW"
    return "GREEN"


def alert_label(level: str) -> str:
    return {
        "GREEN": "Stable",
        "YELLOW": "Watch",
        "ORANGE": "Fragile",
        "RED": "Critical",
        "BLACK": "Collapse",
    }.get(level, level)


def risk_word(score_0_100: float) -> str:
    if score_0_100 >= 80:
        return "CRITICAL"
    if score_0_100 >= 65:
        return "HIGH"
    if score_0_100 >= 45:
        return "ELEVATED"
    if score_0_100 >= 25:
        return "GUARDED"
    return "LOW"


def confidence_word(keyword_hits: int, gt_score_count: int, has_history: bool) -> str:
    """Sparse feeds → lower confidence."""
    points = 0
    if keyword_hits >= 4:
        points += 2
    elif keyword_hits >= 1:
        points += 1
    if gt_score_count >= 2:
        points += 2
    elif gt_score_count >= 1:
        points += 1
    if has_history:
        points += 1
    if points >= 4:
        return "High"
    if points >= 2:
        return "Medium"
    return "Low"


def threat_meter_line(score_0_100: float) -> list[str]:
    """ASCII threat gauge across LOW → CRITICAL."""
    s = max(0.0, min(100.0, score_0_100))
    # 40-char track; mark position
    width = 40
    pos = int(round((s / 100.0) * (width - 1)))
    track = ["-"] * width
    for i in range(max(0, pos - 2), min(width, pos + 3)):
        track[i] = "█"
    bar = "".join(track)
    return [
        "Global Strategic Risk",
        "",
        "LOW    GUARDED    ELEVATED    HIGH    CRITICAL",
        f"|{bar}|",
        f"{' ' * max(0, pos - 1)}{s:.0f} / 100",
    ]


def stability_bar(score_0_100: float, width: int = 24) -> str:
    filled = int(round((max(0.0, min(100.0, score_0_100)) / 100.0) * width))
    return "█" * filled + "░" * (width - filled)


def sparkline(values: list[float], width: int = 30) -> str:
    """Tiny unicode sparkline from a series of 0–100 scores (default ~30 cycles)."""
    if not values:
        return "·" * min(8, width)
    blocks = "▁▂▃▄▅▆▇█"
    series = values[-width:]
    lo, hi = min(series), max(series)
    span = hi - lo if hi > lo else 1.0
    out = []
    for v in series:
        idx = int(round((v - lo) / span * (len(blocks) - 1)))
        out.append(blocks[max(0, min(len(blocks) - 1, idx))])
    return "".join(out)


def confidence_dots(level: str) -> str:
    """●●●○○ style data-quality indicator."""
    filled = {"High": 5, "Medium": 3, "Low": 1}.get(str(level), 2)
    filled = max(0, min(5, filled))
    return "●" * filled + "○" * (5 - filled)


def alert_icon(level: str) -> str:
    return {
        "GREEN": "✓",
        "YELLOW": "▲",
        "ORANGE": "⚠",
        "RED": "⚠",
        "BLACK": "⛔",
    }.get(str(level), "·")


def change_badge(delta: float, *, first_run: bool = False) -> str:
    if first_run:
        return "NEW"
    if abs(delta) < 0.5:
        return "—"
    sign = "▲" if delta > 0 else "▼"
    return f"{sign} {delta:+.0f}"


def progress_bar_ascii(score_0_100: float, width: int = 20) -> str:
    filled = int(round((max(0.0, min(100.0, score_0_100)) / 100.0) * width))
    return "█" * filled + "░" * (width - filled)


def trend_arrows(delta: float, *, step: float = 5.0) -> str:
    if abs(delta) < step * 0.4:
        return "→"
    n = min(3, max(1, int(abs(delta) / step)))
    return ("▲" if delta > 0 else "▼") * n


def _region_features(gt_risk: dict[str, Any] | None) -> list[dict[str, Any]]:
    feats = ((gt_risk or {}).get("heatmap") or {}).get("features") or []
    out = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        region = str(props.get("region") or "").strip()
        if not region:
            continue
        out.append(
            {
                "region": region,
                "risk": float(props.get("risk") or 0.0),
                "conflict": float(props.get("conflict") or 0.0),
                "unrest": float(props.get("unrest") or 0.0),
                "risk_delta": float(props.get("risk_delta") or 0.0),
                "ignition": bool(props.get("micro_ignition")),
            }
        )
    return out


def _fp_drivers(
    fp: dict[str, Any],
    prev: dict[str, Any],
) -> list[str]:
    """Human-readable drivers for a flashpoint move."""
    drivers: list[str] = []
    det = float((fp.get("deterrence") or {}).get("score") or 50)
    old_det = float((prev.get("deterrence") or {}).get("score") or det)
    nash = float(fp.get("nash_score") or 50)
    old_nash = float(prev.get("nash_score") or nash)
    hits = int(fp.get("keyword_hits") or 0)
    old_hits = int(prev.get("keyword_hits") or 0)
    max_gt = float((fp.get("deterrence") or {}).get("max_gt_risk") or 0)
    old_gt = float((prev.get("deterrence") or {}).get("max_gt_risk") or max_gt)
    arrow = (fp.get("arrow") or {}).get("label") or ""

    if det < old_det - 3:
        drivers.append("Deterrence posture weakened")
    elif det > old_det + 3:
        drivers.append("Deterrence posture improved")
    if nash < old_nash - 5:
        drivers.append("Nash stability declined (play off equilibrium)")
    elif nash > old_nash + 5:
        drivers.append("Nash stability improved (closer to equilibrium)")
    if hits > old_hits and hits >= 2:
        drivers.append(f"Escalatory feed signals rose ({hits} keyword hits)")
    elif hits == 0 and old_hits == 0:
        drivers.append("Sparse open-source chatter (low signal density)")
    if max_gt > old_gt + 0.05:
        drivers.append("Underlying GT conflict/unrest risk increased")
    elif max_gt < old_gt - 0.05:
        drivers.append("Underlying GT risk eased")
    if arrow == "toward_eq":
        drivers.append("Inferred actor moves trending toward equilibrium")
    elif arrow == "equilibrium":
        drivers.append("Current play sits on a pure-strategy equilibrium")
    if not drivers:
        drivers.append("No dominant single driver — composite score drift")
    return drivers[:4]


def _flashpoint_priority_key(fp: dict[str, Any]) -> tuple:
    """Worse first: low deterrence, unstable Nash, then large negative Δ."""
    det = float((fp.get("deterrence") or {}).get("score") or 50)
    nash = float(fp.get("nash_score") or 50)
    det_delta = float(fp.get("det_delta") or 0)
    return (det, nash, det_delta)


def compute_deltas(
    gt_risk: dict[str, Any] | None,
    previous_snapshot: dict[str, Any] | None,
    *,
    telegram: dict[str, Any] | None = None,
    reddit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare current GT heatmap + strategic analysis to last report snapshot."""
    threshold = delta_threshold()
    current = {r["region"]: r for r in _region_features(gt_risk)}
    prev_regions = (previous_snapshot or {}).get("regions") or {}
    shifts: list[dict[str, Any]] = []

    for region, row in current.items():
        old = prev_regions.get(region) or {}
        old_risk = float(old.get("risk") or 0.0)
        delta = row["risk"] - old_risk
        micro = float(row.get("risk_delta") or 0.0)
        meaningful = abs(delta) >= threshold or abs(micro) >= threshold or row.get("ignition")
        if meaningful:
            shifts.append(
                {
                    "region": region,
                    "risk": row["risk"],
                    "prev_risk": old_risk,
                    "delta": round(delta, 4),
                    "micro_delta": round(micro, 4),
                    "ignition": bool(row.get("ignition")),
                    "conflict": row["conflict"],
                    "unrest": row["unrest"],
                }
            )

    shifts.sort(key=lambda s: abs(float(s.get("delta") or 0)), reverse=True)

    from analytics.nash_deterrence import build_strategic_analysis

    strategic = build_strategic_analysis(
        gt_risk=gt_risk, telegram=telegram, reddit=reddit
    )
    prev_fp = {
        f.get("id"): f
        for f in ((previous_snapshot or {}).get("flashpoints") or [])
        if isinstance(f, dict)
    }
    # ~30 samples (~days if daily; cycles if 6h reports)
    history_map: dict[str, list[float]] = {
        str(k): list(v) if isinstance(v, list) else []
        for k, v in dict((previous_snapshot or {}).get("det_history") or {}).items()
    }

    enriched_fps: list[dict[str, Any]] = []
    fp_shifts: list[dict[str, Any]] = []
    first_run = not previous_snapshot
    for fp in strategic.get("flashpoints") or []:
        pid = str(fp.get("id") or "")
        old = prev_fp.get(pid) or {}
        new_det = float((fp.get("deterrence") or {}).get("score") or 50)
        old_det = float((old.get("deterrence") or {}).get("score") or new_det)
        new_nash = float(fp.get("nash_score") or 50)
        old_nash = float(old.get("nash_score") or new_nash)
        det_delta = round(new_det - old_det, 1)
        nash_delta = round(new_nash - old_nash, 1)
        series = list(history_map.get(pid) or [])
        series.append(new_det)
        series = series[-30:]
        history_map[pid] = series
        level = alert_level(new_det, new_nash, str(fp.get("nash_band") or ""))
        conf = confidence_word(
            int(fp.get("keyword_hits") or 0),
            len(fp.get("gt_scores") or {}),
            len(series) >= 2,
        )
        row = {
            **fp,
            "prev_deterrence": old_det,
            "prev_nash": old_nash,
            "det_delta": det_delta,
            "nash_delta": nash_delta,
            "alert_level": level,
            "alert_label": alert_label(level),
            "confidence": conf,
            "confidence_dots": confidence_dots(conf),
            "alert_icon": alert_icon(level),
            "change_badge": change_badge(det_delta, first_run=first_run or not old),
            "drivers": _fp_drivers(fp, old),
            "det_history": series,
            "sparkline": sparkline(series, width=30),
            "theater": _THEATER_MAP.get(pid, "Other"),
        }
        enriched_fps.append(row)
        if abs(det_delta) >= 5 or abs(nash_delta) >= 5 or not old or level in {"RED", "BLACK"}:
            fp_shifts.append(row)

    enriched_fps.sort(key=_flashpoint_priority_key)
    fp_shifts.sort(key=lambda f: float(f.get("det_delta") or 0))

    us_cities = (gt_risk or {}).get("us_cities") or {}
    cities = list(us_cities.get("cities") or [])[:8]

    feed_health = _build_feed_health(gt_risk, telegram, reddit)

    has_signal = bool(shifts[:5] or fp_shifts or any(c.get("ignition") for c in shifts))

    return {
        "has_meaningful_change": has_signal or first_run,
        "first_run": first_run,
        "top_region_shifts": shifts[:8],
        "flashpoint_shifts": fp_shifts[:12],
        "flashpoints_ranked": enriched_fps,
        "us_cities": cities,
        "strategic": strategic,
        "regions": current,
        "threshold": threshold,
        "det_history": history_map,
        "previous_generated_at": (previous_snapshot or {}).get("generated_at"),
        "feed_health": feed_health,
    }


# ── Feed health + live snapshot helpers ─────────────────────────────────────


def _feed_post_count(payload: dict[str, Any] | None) -> int:
    """Prefer explicit total, fall back to posts list length."""
    if not isinstance(payload, dict):
        return 0
    try:
        total = int(payload.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    posts = payload.get("posts") or []
    n_posts = len(posts) if isinstance(posts, list) else 0
    return max(total, n_posts)


def _feed_status(count: int, *, ok_at: int = 1, healthy_at: int = 20) -> str:
    if count >= healthy_at:
        return "ok"
    if count >= ok_at:
        return "limited"
    return "sparse"


def _build_feed_health(
    gt_risk: dict[str, Any] | None,
    telegram: dict[str, Any] | None,
    reddit: dict[str, Any] | None,
) -> dict[str, Any]:
    tg = telegram if isinstance(telegram, dict) else {}
    rd = reddit if isinstance(reddit, dict) else {}
    gt = gt_risk if isinstance(gt_risk, dict) else {}

    tg_posts = _feed_post_count(tg)
    rd_posts = _feed_post_count(rd)
    try:
        tg_geo = int(tg.get("geolocated") or 0)
    except (TypeError, ValueError):
        tg_geo = 0
    try:
        rd_geo = int(rd.get("geolocated") or 0)
    except (TypeError, ValueError):
        rd_geo = 0

    channels = tg.get("channels") or []
    subs = rd.get("subreddits") or []
    n_channels = len(channels) if isinstance(channels, list) else 0
    n_subs = len(subs) if isinstance(subs, list) else 0

    gt_feats = len((gt.get("heatmap") or {}).get("features") or [])
    try:
        gt_regions = int(gt.get("regions") or gt_feats or 0)
    except (TypeError, ValueError):
        gt_regions = gt_feats
    try:
        gt_processed = int(gt.get("processed") or 0)
    except (TypeError, ValueError):
        gt_processed = 0

    return {
        "telegram_posts": tg_posts,
        "telegram_geolocated": tg_geo,
        "telegram_channels": n_channels,
        "telegram_status": _feed_status(tg_posts, healthy_at=15),
        "telegram_timestamp": tg.get("timestamp"),
        "reddit_posts": rd_posts,
        "reddit_geolocated": rd_geo,
        "reddit_subreddits": n_subs,
        "reddit_status": _feed_status(rd_posts, healthy_at=20),
        "reddit_timestamp": rd.get("timestamp"),
        "gt_features": max(gt_feats, gt_regions),
        "gt_processed": gt_processed,
        "gt_enabled": bool(gt.get("enabled")),
        "gt_status": "ok" if gt_feats > 0 or gt_regions > 0 else "sparse",
        "gt_timestamp": gt.get("timestamp"),
    }


def _http_get_json(url: str, *, timeout: float = 45.0) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Shadowbroker-DeltaReport/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("feed snapshot HTTP fetch failed %s: %s", url, exc)
        return None


def _snapshot_intel_layers(
    *,
    gt_risk: dict[str, Any] | None = None,
    telegram: dict[str, Any] | None = None,
    reddit: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Load GT + Telegram + Reddit for reporting.

    Prefer the live in-process store (API worker). If empty (e.g. one-shot
    docker exec script), fall back to localhost /api/live-data.
    """
    store_gt: dict[str, Any] = {}
    store_tg: dict[str, Any] = {}
    store_rd: dict[str, Any] = {}
    try:
        from services.fetchers._store import latest_data

        store_gt = dict(latest_data.get("gt_risk") or {})
        store_tg = dict(latest_data.get("telegram_osint") or {})
        store_rd = dict(latest_data.get("reddit_osint") or {})
    except Exception:
        pass

    out_gt = gt_risk if isinstance(gt_risk, dict) and gt_risk else store_gt
    out_tg = telegram if isinstance(telegram, dict) and telegram else store_tg
    out_rd = reddit if isinstance(reddit, dict) and reddit else store_rd

    need_http = (
        _feed_post_count(out_tg) == 0
        or _feed_post_count(out_rd) == 0
        or not ((out_gt.get("heatmap") or {}).get("features"))
    )
    if need_http:
        live = None
        for base in (
            "http://127.0.0.1:8000/api/live-data",
            "http://127.0.0.1:3050/api/live-data",
            "http://localhost:8000/api/live-data",
        ):
            live = _http_get_json(base)
            if live:
                break
        if live:
            if _feed_post_count(out_tg) == 0 and isinstance(live.get("telegram_osint"), dict):
                out_tg = dict(live["telegram_osint"])
            if _feed_post_count(out_rd) == 0 and isinstance(live.get("reddit_osint"), dict):
                out_rd = dict(live["reddit_osint"])
            if not ((out_gt.get("heatmap") or {}).get("features")) and isinstance(
                live.get("gt_risk"), dict
            ):
                out_gt = dict(live["gt_risk"])

    return out_gt or {}, out_tg or {}, out_rd or {}


def _global_risk_score(delta: dict[str, Any]) -> float:
    """0–100 composite from flashpoint fragility + GT shifts."""
    fps = delta.get("flashpoints_ranked") or []
    if fps:
        dets = [float((f.get("deterrence") or {}).get("score") or 50) for f in fps]
        avg_det = sum(dets) / len(dets)
        fragile = sum(1 for f in fps if f.get("alert_level") in {"ORANGE", "RED", "BLACK"})
        fragile_ratio = fragile / max(1, len(fps))
        # Invert deterrence: low det → high risk
        score = (100.0 - avg_det) * 0.65 + fragile_ratio * 35.0
    else:
        shifts = delta.get("top_region_shifts") or []
        if shifts:
            score = min(100.0, max(float(s.get("risk") or 0) for s in shifts) * 100)
        else:
            score = 35.0
    return round(max(0.0, min(100.0, score)), 1)


def _trend_word(delta: dict[str, Any]) -> str:
    fps = delta.get("flashpoints_ranked") or []
    if not fps or delta.get("first_run"):
        return "▲ Baseline established" if delta.get("first_run") else "→ Steady"
    det_deltas = [float(f.get("det_delta") or 0) for f in fps]
    avg = sum(det_deltas) / len(det_deltas)
    wors = sum(1 for d in det_deltas if d <= -5)
    imp = sum(1 for d in det_deltas if d >= 5)
    if wors > imp and avg < -2:
        return "▲ Worsening"
    if imp > wors and avg > 2:
        return "▼ Improving"
    return "→ Mixed / steady"


def _posture_block(delta: dict[str, Any], risk_score: float) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    critical = sum(1 for f in fps if f.get("alert_level") in {"RED", "BLACK"})
    fragile = sum(1 for f in fps if f.get("alert_level") == "ORANGE")
    stable = sum(1 for f in fps if f.get("alert_level") == "GREEN")
    sig = len(delta.get("flashpoint_shifts") or []) + len(
        [s for s in (delta.get("top_region_shifts") or []) if abs(float(s.get("delta") or 0)) >= delta_threshold()]
    )
    confs = [f.get("confidence") for f in fps]
    if confs.count("High") >= len(confs) / 2 and confs:
        conf = "High"
    elif confs.count("Low") >= len(confs) / 2 and confs:
        conf = "Low"
    else:
        conf = "Medium"

    return [
        _HR,
        "GLOBAL STRATEGIC POSTURE",
        _HR,
        "",
        f"Overall Risk:          {risk_word(risk_score)}",
        f"Trend:                 {_trend_word(delta)}",
        f"Significant Changes:   {sig}",
        f"Critical Flashpoints:  {critical}",
        f"Fragile (ORANGE):      {fragile}",
        f"Stable Regions:        {stable}",
        f"Confidence:            {conf}",
        "",
    ]


def _executive_assessment(delta: dict[str, Any], risk_score: float) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    wors = sorted(fps, key=lambda f: float(f.get("det_delta") or 0))[:3]
    best = sorted(fps, key=lambda f: float(f.get("det_delta") or 0), reverse=True)[:2]
    theaters: dict[str, int] = {}
    for f in fps:
        if f.get("alert_level") in {"ORANGE", "RED", "BLACK"}:
            t = str(f.get("theater") or "Other")
            theaters[t] = theaters.get(t, 0) + 1
    hot_theater = max(theaters, key=theaters.get) if theaters else "none"
    cities = delta.get("us_cities") or []
    hot_city = None
    for c in cities:
        if float(c.get("protest_potential") or 0) >= 0.35 or int(c.get("protest_mentions") or 0) >= 5:
            hot_city = c.get("label")
            break

    if delta.get("first_run"):
        para = (
            f"Baseline strategic snapshot established. Overall risk is scored "
            f"{risk_word(risk_score)} ({risk_score:.0f}/100). "
            f"{len(fps)} flashpoints are under continuous watch. "
            f"{'Domestic protest watch flags ' + str(hot_city) + '. ' if hot_city else 'No domestic protest hotspot exceeds elevated watch. '}"
            f"Subsequent cycles will emphasize movement versus this baseline."
        )
    else:
        names = ", ".join(str(f.get("label")) for f in wors if float(f.get("det_delta") or 0) < 0) or "none"
        gains = ", ".join(str(f.get("label")) for f in best if float(f.get("det_delta") or 0) > 0) or "none"
        para = (
            f"The strategic environment is {risk_word(risk_score).lower()} this cycle "
            f"({risk_score:.0f}/100; {_trend_word(delta)}). "
            f"Largest deteriorations: {names}. "
            f"Improvements: {gains}. "
            f"Instability concentration: {hot_theater}. "
            f"{'Domestic watch: ' + str(hot_city) + '. ' if hot_city else 'No US metro exceeds elevated protest thresholds. '}"
            f"Operators should prioritize flashpoints listed under Priority Watch below."
        )

    return [
        "EXECUTIVE ASSESSMENT",
        _HR,
        "",
        para,
        "",
    ]


def _biggest_movers(delta: dict[str, Any]) -> list[str]:
    fps = list(delta.get("flashpoints_ranked") or [])
    if delta.get("first_run"):
        return [
            "TOP CHANGES",
            _HR,
            "",
            "Baseline cycle — no prior report for movement comparison.",
            "All flashpoints treated as initial observations.",
            "",
        ]
    improve = [f for f in fps if float(f.get("det_delta") or 0) >= 3]
    worsen = [f for f in fps if float(f.get("det_delta") or 0) <= -3]
    improve.sort(key=lambda f: float(f.get("det_delta") or 0), reverse=True)
    worsen.sort(key=lambda f: float(f.get("det_delta") or 0))
    lines = ["TOP CHANGES", _HR, "", "Top Improvements", ""]
    if improve:
        for f in improve[:5]:
            d = float(f.get("det_delta") or 0)
            lines.append(f"  ▲ {f.get('label'):<28} {d:+.0f}  {trend_arrows(d)}")
    else:
        lines.append("  (none above +3 deterrence)")
    lines += ["", "Top Deteriorations", ""]
    if worsen:
        for f in worsen[:5]:
            d = float(f.get("det_delta") or 0)
            lines.append(f"  ▼ {f.get('label'):<28} {d:+.0f}  {trend_arrows(d)}")
    else:
        lines.append("  (none below −3 deterrence)")
    lines.append("")
    return lines


def _new_since_previous(delta: dict[str, Any]) -> list[str]:
    lines = ["WHAT CHANGED SINCE PREVIOUS REPORT", _HR, ""]
    if delta.get("first_run"):
        lines += ["• First report in this node’s cycle history (baseline).", ""]
        return lines
    bullets: list[str] = []
    for f in delta.get("flashpoints_ranked") or []:
        det = float((f.get("deterrence") or {}).get("score") or 50)
        prev = float(f.get("prev_deterrence") or det)
        level = f.get("alert_level")
        if det < 35 <= prev:
            bullets.append(f"• {f.get('label')} deterrence fell into {level} ({alert_label(str(level))}).")
        if f.get("nash_band") == "unstable" and float(f.get("prev_nash") or 50) >= 45:
            bullets.append(f"• {f.get('label')} entered unstable Nash band.")
        if float(f.get("det_delta") or 0) <= -10:
            bullets.append(
                f"• {f.get('label')} deterrence dropped {float(f.get('det_delta') or 0):.0f} points "
                f"(largest-class move)."
            )
    for s in (delta.get("top_region_shifts") or [])[:4]:
        if s.get("ignition"):
            bullets.append(f"• GT ignition: {s.get('region')} (micro spike).")
        elif abs(float(s.get("delta") or 0)) >= 0.15:
            bullets.append(
                f"• Region {s.get('region')} risk "
                f"{float(s.get('prev_risk') or 0):.0%} → {float(s.get('risk') or 0):.0%}."
            )
    cities = delta.get("us_cities") or []
    elevated = [
        c
        for c in cities
        if float(c.get("protest_potential") or 0) >= 0.35 or int(c.get("protest_mentions") or 0) >= 5
    ]
    if elevated:
        bullets.append(
            "• US protest watch active: "
            + ", ".join(str(c.get("label")) for c in elevated[:4])
            + "."
        )
    else:
        bullets.append("• No new US protest hotspots above elevated watch.")
    # Stability streaks from history length + flat delta
    for f in delta.get("flashpoints_ranked") or []:
        if f.get("alert_level") == "GREEN" and abs(float(f.get("det_delta") or 0)) < 3:
            hist = f.get("det_history") or []
            if len(hist) >= 2:
                bullets.append(f"• {f.get('label')} remained stable this cycle.")
                break
    if not bullets:
        bullets.append("• No threshold crossings; residual score drift only.")
    lines.extend(bullets[:12])
    lines.append("")
    return lines


def _statistics(delta: dict[str, Any]) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    n = len(fps)
    warn = sum(1 for f in fps if f.get("alert_level") in {"YELLOW", "ORANGE", "RED", "BLACK"})
    crit = sum(1 for f in fps if f.get("alert_level") in {"RED", "BLACK"})
    imp = sum(1 for f in fps if float(f.get("det_delta") or 0) >= 3)
    wors = sum(1 for f in fps if float(f.get("det_delta") or 0) <= -3)
    stable = sum(1 for f in fps if f.get("alert_level") == "GREEN")
    return [
        "STATISTICS",
        _HR,
        "",
        f"Flashpoints monitored      {n}",
        f"Above warning threshold     {warn}",
        f"Critical                    {crit}",
        f"Improving                   {imp}",
        f"Worsening                   {wors}",
        f"Stable (GREEN)              {stable}",
        f"GT region shifts logged     {len(delta.get('top_region_shifts') or [])}",
        "",
    ]


def _flashpoint_watch(delta: dict[str, Any]) -> list[str]:
    lines = ["FLASHPOINT WATCH (priority order)", _HR, ""]
    fps = delta.get("flashpoints_ranked") or []
    if not fps:
        lines += ["_No flashpoints available._", ""]
        return lines
    for i, f in enumerate(fps, 1):
        det = float((f.get("deterrence") or {}).get("score") or 0)
        prev = float(f.get("prev_deterrence") or det)
        nash = float(f.get("nash_score") or 0)
        d_det = float(f.get("det_delta") or 0)
        badge = f.get("change_badge") or change_badge(d_det, first_run=bool(delta.get("first_run")))
        icon = f.get("alert_icon") or alert_icon(str(f.get("alert_level") or ""))
        dots = f.get("confidence_dots") or confidence_dots(str(f.get("confidence") or "Low"))
        lines += [
            f"Priority {i}  ·  {icon} {f.get('label')}  [{badge}]",
            "─" * 40,
            f"Alert:        {f.get('alert_level')} — {f.get('alert_label')}",
            f"Deterrence:   {progress_bar_ascii(det)} {det:.0f}"
            + (
                f"  ({prev:.0f} → {det:.0f}  {trend_arrows(d_det)}{abs(d_det):.0f})"
                if not delta.get("first_run")
                else "  (baseline)"
            ),
            f"Nash:         {progress_bar_ascii(nash)} {nash:.0f} ({f.get('nash_band')})",
            f"Confidence:   {dots}  {f.get('confidence')}",
            f"Trend (30):   {f.get('sparkline')}",
            "",
            "Primary Drivers",
        ]
        for d in f.get("drivers") or []:
            lines.append(f"  • {d}")
        # Why it matters
        if i == 1 and d_det <= -5:
            lines += ["", "Assessment", f"  Largest deterioration this cycle ({d_det:+.0f} deterrence)."]
        elif f.get("alert_level") in {"RED", "BLACK"}:
            lines += ["", "Assessment", "  Elevated attention recommended — critical alert band."]
        lines.append("")
    return lines


def _regional_heat(delta: dict[str, Any]) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    theaters: dict[str, list[float]] = {}
    for f in fps:
        t = str(f.get("theater") or "Other")
        # Invert det for "instability" heat 0–100
        det = float((f.get("deterrence") or {}).get("score") or 50)
        theaters.setdefault(t, []).append(100.0 - det)
    # Also fold US domestic as North America if cities elevated
    cities = delta.get("us_cities") or []
    if cities:
        pot = max(float(c.get("protest_potential") or 0) for c in cities) * 100
        theaters.setdefault("North America", []).append(pot)
    lines = ["REGIONAL STABILITY HEAT", _HR, "", "(higher bar = more instability)", ""]
    if not theaters:
        lines += ["_No theater data._", ""]
        return lines
    ranked = sorted(
        ((t, sum(v) / len(v)) for t, v in theaters.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    for t, heat in ranked:
        lines.append(f"{stability_bar(heat, 10)}  {t:<16}  {heat:.0f}")
    lines.append("")
    return lines


def _domestic(delta: dict[str, Any]) -> list[str]:
    lines = ["DOMESTIC STABILITY (US Protest Watch)", _HR, ""]
    cities = delta.get("us_cities") or []
    if not cities:
        lines += ["No elevated US metros in this snapshot.", ""]
        return lines
    lines.append("| Metro | Potential | Unrest | Hits | Confidence |")
    lines.append("|-------|-----------|--------|------|------------|")
    for c in cities:
        pot = float(c.get("protest_potential") or 0)
        conf = "High" if int(c.get("protest_mentions") or 0) >= 5 else (
            "Medium" if int(c.get("protest_mentions") or 0) >= 1 else "Low"
        )
        lines.append(
            f"| {c.get('label')} | {pot:.0%} | {float(c.get('unrest') or 0):.0%} | "
            f"{c.get('protest_mentions', 0)} | {conf} |"
        )
    lines.append("")
    return lines


def _watch_conditions(delta: dict[str, Any]) -> list[str]:
    lines = ["WATCH CONDITIONS", _HR, ""]
    fps = delta.get("flashpoints_ranked") or []
    if not fps:
        lines += ["_None._", ""]
        return lines
    for f in fps:
        det = float((f.get("deterrence") or {}).get("score") or 50)
        nash = float(f.get("nash_score") or 50)
        # Next threshold just below current band
        if det >= 50:
            trig = f"Deterrence < 50 (enter ORANGE/Fragile)"
        elif det >= 35:
            trig = f"Deterrence < 35 (enter RED/Critical)"
        else:
            trig = f"Deterrence < 20 (enter BLACK/Collapse)"
        nash_trig = "Nash < 45 (unstable band)" if nash >= 45 else "Nash < 25 (collapse risk)"
        lines += [
            f"{f.get('label')}",
            f"  Next alert trigger:  {trig}",
            f"  Secondary trigger:   {nash_trig}",
            "",
        ]
    # GT region watch
    for s in (delta.get("top_region_shifts") or [])[:3]:
        risk = float(s.get("risk") or 0)
        lines.append(f"GT region {s.get('region')}")
        lines.append(f"  Next alert trigger:  Risk > {min(0.99, risk + 0.08):.2f}")
        lines.append("")
    return lines


def _analyst_note(delta: dict[str, Any]) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    notes: list[str] = []
    # Coupling: similar det scores in same theater
    by_theater: dict[str, list[dict[str, Any]]] = {}
    for f in fps:
        by_theater.setdefault(str(f.get("theater") or "Other"), []).append(f)
    for theater, group in by_theater.items():
        if len(group) < 2:
            continue
        scores = [float((g.get("deterrence") or {}).get("score") or 0) for g in group]
        if max(scores) - min(scores) <= 8 and min(scores) < 55:
            names = " and ".join(str(g.get("label")) for g in group[:2])
            notes.append(
                f"{names} now share nearly identical deterrence indices in {theater}. "
                f"This may indicate increasing strategic coupling."
            )
    # Simultaneous multi-theater stress
    stressed = {str(f.get("theater")) for f in fps if f.get("alert_level") in {"ORANGE", "RED", "BLACK"}}
    if len(stressed) >= 2:
        notes.append(
            f"Simultaneous stress across {', '.join(sorted(stressed))} increases "
            f"overall escalation risk beyond any single theater."
        )
    if not notes:
        notes.append(
            "No strong cross-flashpoint coupling detected this cycle. "
            "Monitor Indo-Pacific and European theaters independently."
        )
    lines = ["ANALYST NOTE", _HR, ""]
    for n in notes[:2]:
        lines.append(n)
        lines.append("")
    return lines


def _outlook(delta: dict[str, Any], risk_score: float) -> list[str]:
    fps = delta.get("flashpoints_ranked") or []
    worst = fps[0] if fps else None
    best = None
    if fps:
        best = max(fps, key=lambda f: float((f.get("deterrence") or {}).get("score") or 0))
    wors_count = sum(1 for f in fps if float(f.get("det_delta") or 0) <= -5)
    if risk_score >= 65 or wors_count >= 2:
        likelihood = "HIGH"
        mon = "Continuous"
    elif risk_score >= 45 or wors_count >= 1:
        likelihood = "MODERATE"
        mon = "Elevated"
    else:
        likelihood = "LOW"
        mon = "Routine"
    return [
        "24-HOUR OUTLOOK",
        _HR,
        "",
        f"Likelihood of additional deterioration:  {likelihood}",
        f"Most likely area of movement:            {worst.get('label') if worst else 'n/a'}",
        f"Most stable region:                      {best.get('label') if best else 'n/a'}",
        f"Recommended monitoring:                  {mon}",
        "",
    ]


def _methodology() -> list[str]:
    return [
        "METHODOLOGY",
        _HR,
        "",
        "• Self-hosted analysis only; no external LLM required.",
        "• Nash scores: pure-strategy 2×2 equilibria fused with live GT risk.",
        "• Deterrence: operational index (Nash stability − GT risk − feed heat).",
        "• Alert bands: GREEN/YELLOW/ORANGE/RED/BLACK from deterrence + Nash.",
        "• Confidence reflects feed density and GT region coverage — not certainty of outcomes.",
        "• Deltas compare this cycle to the previous delivered report on this node.",
        "",
    ]


def _exec_summary(delta: dict[str, Any]) -> list[str]:
    """Short bullets for API/webhook consumers."""
    risk = _global_risk_score(delta)
    lines = [
        f"Posture: {risk_word(risk)} ({risk:.0f}/100) · {_trend_word(delta)}",
    ]
    for f in (delta.get("flashpoints_ranked") or [])[:3]:
        d = float(f.get("det_delta") or 0)
        lines.append(
            f"{f.get('label')}: det {(f.get('deterrence') or {}).get('score')} "
            f"({d:+.0f}) · {f.get('alert_level')}"
        )
    for s in (delta.get("top_region_shifts") or [])[:2]:
        lines.append(
            f"GT {s.get('region')}: {float(s.get('prev_risk') or 0):.0%}→"
            f"{float(s.get('risk') or 0):.0%}"
        )
    return lines[:6]


def render_markdown(delta: dict[str, Any], *, generated_at: str) -> str:
    """Decision-support briefing markdown."""
    risk_score = _global_risk_score(delta)
    prev_at = delta.get("previous_generated_at") or "none"
    header = [
        "# Shadowbroker Strategic Delta Brief",
        "",
        f"**Generated:** {generated_at}",
        f"**Compared to:** {prev_at}",
        f"**Cycle type:** {'BASELINE' if delta.get('first_run') else 'DELTA'}",
        f"**Change threshold:** |Δrisk| ≥ {delta.get('threshold')}",
        "",
    ]
    sections: list[str] = []
    for block in (
        header,
        _posture_block(delta, risk_score),
        threat_meter_line(risk_score) + [""],
        ["Strategic Stability", "", f"{stability_bar(100.0 - risk_score)}", f"{100.0 - risk_score:.0f}% (higher = more stable)", ""],
        _executive_assessment(delta, risk_score),
        _new_since_previous(delta),
        _biggest_movers(delta),
        _statistics(delta),
        _flashpoint_watch(delta),
        _regional_heat(delta),
        _domestic(delta),
        _watch_conditions(delta),
        _analyst_note(delta),
        _outlook(delta, risk_score),
        _methodology(),
    ):
        sections.extend(block)
    return "\n".join(sections)


def _esc(s: Any) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _risk_banner_class(word: str) -> str:
    return {
        "LOW": "banner-low",
        "GUARDED": "banner-guarded",
        "ELEVATED": "banner-elevated",
        "HIGH": "banner-high",
        "CRITICAL": "banner-critical",
    }.get(word, "banner-elevated")


def _level_class(level: str) -> str:
    return {
        "GREEN": "lvl-green",
        "YELLOW": "lvl-yellow",
        "ORANGE": "lvl-orange",
        "RED": "lvl-red",
        "BLACK": "lvl-black",
    }.get(str(level), "lvl-yellow")


def _badge_class(badge: str) -> str:
    if badge.startswith("▲") or "+" in badge:
        return "badge-up"
    if badge.startswith("▼") or badge.startswith("-"):
        return "badge-down"
    if badge == "NEW":
        return "badge-new"
    return "badge-flat"


def _html_progress(score: float, kind: str = "det") -> str:
    s = max(0.0, min(100.0, float(score)))
    # Deterrence: high=good (green); risk: high=bad (red) — invert color for det
    if kind == "det":
        color = "#22c55e" if s >= 65 else ("#f59e0b" if s >= 40 else "#ef4444")
    else:
        color = "#ef4444" if s >= 65 else ("#f59e0b" if s >= 40 else "#22c55e")
    return (
        f'<div class="pbar"><div class="pbar-fill" style="width:{s:.1f}%;background:{color}"></div>'
        f'<span class="pbar-label">{s:.0f}</span></div>'
    )


def _html_spark_svg(values: list[float], *, width: int = 120, height: int = 28) -> str:
    if not values:
        return f'<svg class="spark" width="{width}" height="{height}"></svg>'
    series = [float(v) for v in values[-30:]]
    lo, hi = min(series), max(series)
    span = hi - lo if hi > lo else 1.0
    n = len(series)
    pts = []
    for i, v in enumerate(series):
        x = 2 + (width - 4) * (i / max(1, n - 1))
        y = height - 3 - ((v - lo) / span) * (height - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    last = series[-1]
    color = "#ef4444" if last < 40 else ("#f59e0b" if last < 65 else "#22c55e")
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{poly}"/>'
        f"</svg>"
    )


# --- Theater map base: Mercator PNG (transparent ocean) ---
_MAP_PNG_CACHE: str | None = None
_MAP_PNG_SIZE: tuple[int, int] | None = None


def _map_png_path() -> Path | None:
    """Resolve world mercator asset (repo, container, or Downloads)."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "assets" / "world_mercator.png",
        here.parent / "data" / "assets" / "world_mercator.png",
        Path.home() / "Downloads" / "pngegg.png",
        Path("/app/analytics/assets/world_mercator.png"),
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _map_png_data_uri() -> tuple[str, int, int]:
    """Return (data_uri, width, height). Cached after first load."""
    global _MAP_PNG_CACHE, _MAP_PNG_SIZE
    if _MAP_PNG_CACHE and _MAP_PNG_SIZE:
        return _MAP_PNG_CACHE, _MAP_PNG_SIZE[0], _MAP_PNG_SIZE[1]

    import base64

    path = _map_png_path()
    if path is None:
        return "", 1280, 946
    raw = path.read_bytes()
    w, h = 1280, 946
    try:
        from PIL import Image
        import io

        im = Image.open(io.BytesIO(raw))
        w, h = im.size
    except Exception:
        pass
    uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    _MAP_PNG_CACHE = uri
    _MAP_PNG_SIZE = (w, h)
    return uri, w, h


def _mercator_xy(lng: float, lat: float, w: float, h: float) -> tuple[float, float]:
    """Web Mercator into pixel space matching a full-world PNG (transparent ocean)."""
    import math

    # Clamp to Web Mercator valid range
    max_lat = 85.05112878
    lat = max(-max_lat, min(max_lat, lat))
    x = (float(lng) + 180.0) / 360.0 * w
    lat_rad = math.radians(lat)
    # y in [0,1] top→bottom
    y_norm = (1.0 - math.log(math.tan(math.pi / 4.0 + lat_rad / 2.0)) / math.pi) / 2.0
    y = y_norm * h
    return x, y


def _html_world_map(fps: list[dict[str, Any]]) -> str:
    """Mercator basemap (pngegg/world_mercator.png) + projected flashpoint hotspots."""
    uri, iw, ih = _map_png_data_uri()
    w, h = float(iw), float(ih)

    if not uri:
        # Fallback notice if asset missing
        return (
            f'<svg class="worldmap" viewBox="0 0 640 360" width="100%" role="img">'
            f'<rect width="640" height="360" fill="#0a1628"/>'
            f'<text x="320" y="180" fill="#f87171" text-anchor="middle" '
            f'font-family="ui-monospace,monospace" font-size="14">'
            f"Map asset missing — place world_mercator.png in analytics/assets/"
            f"</text></svg>"
        )

    placed: list[tuple[float, float, dict[str, Any]]] = []
    for f in fps:
        try:
            lat = float(f.get("lat"))
            lng = float(f.get("lng"))
        except (TypeError, ValueError):
            continue
        placed.append((lng, lat, f))
    placed.sort(key=lambda t: t[0])

    dots: list[str] = []
    for idx, (lng, lat, f) in enumerate(placed):
        x, y = _mercator_xy(lng, lat, w, h)
        x = max(6.0, min(w - 6.0, x))
        y = max(6.0, min(h - 6.0, y))
        level = str(f.get("alert_level") or "YELLOW")
        fill = {
            "GREEN": "#22c55e",
            "YELLOW": "#eab308",
            "ORANGE": "#f97316",
            "RED": "#ef4444",
            "BLACK": "#f8fafc",
        }.get(level, "#f59e0b")
        r = 10 if level in {"RED", "BLACK"} else 8
        label = _esc(str(f.get("label") or "")[:24])
        # Stagger callouts
        above = idx % 2 == 0
        right = (idx % 3) != 1
        lx = x + (70 if right else -70)
        ly = y + (-28 if above else 32)
        lx = max(8.0, min(w - 180.0, lx))
        ly = max(16.0, min(h - 12.0, ly))
        box_w = min(176.0, 12 + len(label) * 6.0)
        dots.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" '
            f'stroke="#94a3b8" stroke-width="1.2" opacity="0.85"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 6}" fill="{fill}" opacity="0.22"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="#020617" '
            f'stroke-width="1.6"><title>{label}</title></circle>'
            f'<rect x="{lx - 4:.1f}" y="{ly - 12:.1f}" width="{box_w:.0f}" height="16" rx="2" '
            f'fill="#0b1220f2" stroke="#475569" stroke-width="0.8"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#f1f5f9" font-size="11" '
            f'font-family="ui-monospace,Menlo,monospace" text-anchor="start">{label}</text>'
        )

    # Dark plate behind transparent PNG so land stands out
    bg = (
        f'<rect width="{w:.0f}" height="{h:.0f}" fill="#050a12"/>'
        f'<image href="{uri}" x="0" y="0" width="{w:.0f}" height="{h:.0f}" '
        f'preserveAspectRatio="none"/>'
    )
    legend = (
        f'<g transform="translate(12,{h - 14})">'
        f'<text x="0" y="0" fill="#94a3b8" font-size="11" font-family="ui-monospace,monospace">'
        f"Web Mercator basemap · hotspot color = alert band "
        f"(green stable · yellow watch · orange fragile · red/black critical)"
        f"</text></g>"
    )

    return (
        f'<svg class="worldmap" viewBox="0 0 {w:.0f} {h:.0f}" width="100%" role="img" '
        f'aria-label="Mercator world map with flashpoint hotspots">'
        f"{bg}{''.join(dots)}{legend}"
        f"</svg>"
    )



def render_html(markdown_body: str, *, title: str) -> str:
    """Legacy wrapper — prefer render_html_dashboard when delta payload is available."""
    body = _esc(markdown_body).replace("\n", "<br>\n")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_esc(title)}</title>
<style>
body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background:#0b1220; color:#e2e8f0;
  padding:28px; max-width:920px; margin:auto; line-height:1.45; font-size:13px; }}
h1 {{ color:#fbbf24; font-size:1.35rem; letter-spacing:0.04em; }}
</style></head><body>
{body}
</body></html>"""


def render_html_dashboard(
    delta: dict[str, Any],
    *,
    generated_at: str,
    title: str,
) -> str:
    """NOC / executive SITREP HTML — Bloomberg-dark + Palantir-adjacent."""
    risk = _global_risk_score(delta)
    word = risk_word(risk)
    fps = delta.get("flashpoints_ranked") or []
    feed = delta.get("feed_health") or {}
    first = bool(delta.get("first_run"))

    # Side panel: top movers
    improve = sorted(
        [f for f in fps if float(f.get("det_delta") or 0) >= 3],
        key=lambda f: float(f.get("det_delta") or 0),
        reverse=True,
    )[:4]
    worsen = sorted(
        [f for f in fps if float(f.get("det_delta") or 0) <= -3],
        key=lambda f: float(f.get("det_delta") or 0),
    )[:4]
    emerging = [f for f in fps if f.get("alert_level") in {"ORANGE", "RED", "BLACK"}][:5]

    def mover_row(f: dict[str, Any]) -> str:
        d = float(f.get("det_delta") or 0)
        badge = _esc(f.get("change_badge") or change_badge(d, first_run=first))
        return (
            f'<div class="mover"><span class="mover-name">{_esc(f.get("label"))}</span>'
            f'<span class="badge {_badge_class(badge)}">{badge}</span></div>'
        )

    movers_html = ""
    if first:
        movers_html = '<div class="muted">Baseline cycle — no prior deltas.</div>'
    else:
        movers_html = (
            '<div class="subhead">▲ Improvements</div>'
            + ("".join(mover_row(f) for f in improve) or '<div class="muted">None</div>')
            + '<div class="subhead">▼ Deteriorations</div>'
            + ("".join(mover_row(f) for f in worsen) or '<div class="muted">None</div>')
        )

    emerging_html = "".join(
        f'<div class="mover"><span class="icon">{_esc(f.get("alert_icon"))}</span> '
        f'<span class="mover-name">{_esc(f.get("label"))}</span>'
        f'<span class="lvl {_level_class(str(f.get("alert_level")))}">{_esc(f.get("alert_level"))}</span></div>'
        for f in emerging
    ) or '<div class="muted">No elevated flashpoints</div>'

    def feed_row(name: str, status: str, detail: str) -> str:
        st = str(status or "sparse")
        cls = "ok" if st == "ok" else ("mid" if st == "limited" else "bad")
        return (
            f'<div class="feed-row"><span class="feed-dot {cls}"></span>'
            f"<span>{_esc(name)}</span>"
            f'<span class="muted">{_esc(st)} · {_esc(detail)}</span></div>'
        )

    tg_detail = (
        f"{int(feed.get('telegram_posts') or 0)} posts"
        f" · {int(feed.get('telegram_geolocated') or 0)} geo"
        f" · {int(feed.get('telegram_channels') or 0)} ch"
    )
    rd_detail = (
        f"{int(feed.get('reddit_posts') or 0)} posts"
        f" · {int(feed.get('reddit_geolocated') or 0)} geo"
        f" · {int(feed.get('reddit_subreddits') or 0)} subs"
    )
    gt_detail = (
        f"{int(feed.get('gt_features') or 0)} regions"
        f" · {int(feed.get('gt_processed') or 0)} updates"
    )
    feed_html = (
        feed_row("Telegram OSINT", str(feed.get("telegram_status") or "sparse"), tg_detail)
        + feed_row("Reddit OSINT", str(feed.get("reddit_status") or "sparse"), rd_detail)
        + feed_row("GT heatmap", str(feed.get("gt_status") or "sparse"), gt_detail)
    )

    cards = []
    for i, f in enumerate(fps, 1):
        det = float((f.get("deterrence") or {}).get("score") or 0)
        nash = float(f.get("nash_score") or 0)
        badge = _esc(f.get("change_badge") or "—")
        drivers = "".join(f"<li>{_esc(d)}</li>" for d in (f.get("drivers") or [])[:3])
        hist = list(f.get("det_history") or [])
        cards.append(
            f"""
<article class="fp-card {_level_class(str(f.get("alert_level")))}">
  <header>
    <span class="pri">P{i}</span>
    <span class="icon">{_esc(f.get("alert_icon"))}</span>
    <h3>{_esc(f.get("label"))}</h3>
    <span class="badge {_badge_class(badge)}">{badge}</span>
  </header>
  <div class="fp-meta">
    <span class="lvl {_level_class(str(f.get("alert_level")))}">{_esc(f.get("alert_level"))} · {_esc(f.get("alert_label"))}</span>
    <span class="conf" title="Data confidence">{_esc(f.get("confidence_dots"))} {_esc(f.get("confidence"))}</span>
  </div>
  <div class="metrics">
    <div class="metric"><label>Deterrence</label>{_html_progress(det, "det")}</div>
    <div class="metric"><label>Nash</label>{_html_progress(nash, "det")}</div>
  </div>
  <div class="spark-row">
    <span class="muted">30-cycle trend</span>
    {_html_spark_svg(hist)}
    <code class="spark-txt">{_esc(f.get("sparkline"))}</code>
  </div>
  <ul class="drivers">{drivers}</ul>
</article>"""
        )

    # Executive paragraph (plain text from helper)
    exec_lines = _executive_assessment(delta, risk)
    exec_para = next((ln for ln in exec_lines if ln and not ln.isupper() and "─" not in ln), "")

    outlook_lines = _outlook(delta, risk)
    outlook_bits = [ln for ln in outlook_lines if ":" in ln]

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)}</title>
<style>
:root {{
  --bg: #070b14;
  --panel: #0d1424;
  --panel2: #111b2e;
  --border: #1e2a44;
  --text: #e2e8f0;
  --muted: #64748b;
  --amber: #fbbf24;
  --cyan: #22d3ee;
  --green: #22c55e;
  --yellow: #eab308;
  --orange: #f97316;
  --red: #ef4444;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px; line-height: 1.45;
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 16px 18px 40px; }}
.banner {{
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 16px 20px; border: 1px solid var(--border); border-radius: 2px;
  margin-bottom: 14px; letter-spacing: 0.12em; font-weight: 700; font-size: 1.15rem;
}}
.banner-low {{ background: linear-gradient(90deg,#052e16,#0b1220); color: #86efac; border-color: #166534; }}
.banner-guarded {{ background: linear-gradient(90deg,#1e3a5f,#0b1220); color: #93c5fd; border-color: #1d4ed8; }}
.banner-elevated {{ background: linear-gradient(90deg,#422006,#0b1220); color: #fcd34d; border-color: #b45309; }}
.banner-high {{ background: linear-gradient(90deg,#450a0a,#0b1220); color: #fca5a5; border-color: #b91c1c; }}
.banner-critical {{ background: linear-gradient(90deg,#450a0a,#1a0505); color: #fecaca; border-color: #ef4444;
  box-shadow: 0 0 24px rgba(239,68,68,0.25); }}
.banner .sub {{ font-size: 0.72rem; font-weight: 500; letter-spacing: 0.06em; opacity: 0.85; }}
.grid {{ display: grid; grid-template-columns: 1fr 280px; gap: 12px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.panel {{
  background: var(--panel); border: 1px solid var(--border); border-radius: 2px; padding: 12px 14px;
}}
.panel h2 {{
  margin: 0 0 10px; font-size: 0.7rem; letter-spacing: 0.16em; color: var(--amber);
  font-weight: 700; text-transform: uppercase;
}}
.side {{ display: flex; flex-direction: column; gap: 12px; }}
.muted {{ color: var(--muted); }}
.subhead {{ margin: 8px 0 4px; font-size: 0.65rem; letter-spacing: 0.14em; color: var(--cyan); text-transform: uppercase; }}
.mover {{ display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid #152038; }}
.mover-name {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.badge {{
  font-size: 0.68rem; padding: 1px 6px; border-radius: 2px; border: 1px solid var(--border);
  letter-spacing: 0.04em; white-space: nowrap;
}}
.badge-up {{ color: #86efac; border-color: #166534; background: #052e1688; }}
.badge-down {{ color: #fca5a5; border-color: #991b1b; background: #450a0a88; }}
.badge-new {{ color: #67e8f9; border-color: #0e7490; background: #08334488; }}
.badge-flat {{ color: var(--muted); }}
.lvl {{ font-size: 0.65rem; letter-spacing: 0.08em; padding: 1px 5px; border-radius: 2px; }}
.lvl-green {{ color: #86efac; }}
.lvl-yellow {{ color: #fde047; }}
.lvl-orange {{ color: #fdba74; }}
.lvl-red {{ color: #fca5a5; }}
.lvl-black {{ color: #f8fafc; background: #1e1b1b; }}
.pbar {{
  position: relative; height: 14px; background: #0a1020; border: 1px solid #1e293b;
  border-radius: 1px; overflow: hidden; flex: 1;
}}
.pbar-fill {{ height: 100%; opacity: 0.9; }}
.pbar-label {{
  position: absolute; right: 4px; top: 0; bottom: 0; display: flex; align-items: center;
  font-size: 0.65rem; color: #f8fafc; text-shadow: 0 0 3px #000;
}}
.metric {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.metric label {{ width: 72px; color: var(--muted); font-size: 0.68rem; letter-spacing: 0.06em; }}
.fp-card {{
  border: 1px solid var(--border); background: var(--panel2); padding: 10px 12px; margin-bottom: 8px;
  border-left-width: 3px;
}}
.fp-card.lvl-green {{ border-left-color: var(--green); }}
.fp-card.lvl-yellow {{ border-left-color: var(--yellow); }}
.fp-card.lvl-orange {{ border-left-color: var(--orange); }}
.fp-card.lvl-red {{ border-left-color: var(--red); }}
.fp-card.lvl-black {{ border-left-color: #f8fafc; }}
.fp-card header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
.fp-card h3 {{ margin: 0; flex: 1; font-size: 0.95rem; letter-spacing: 0.04em; }}
.pri {{ color: var(--cyan); font-size: 0.7rem; }}
.fp-meta {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px; }}
.conf {{ color: #94a3b8; letter-spacing: 0.08em; font-size: 0.75rem; }}
.spark-row {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }}
.spark-txt {{ color: #64748b; font-size: 0.65rem; }}
.drivers {{ margin: 6px 0 0; padding-left: 16px; color: #94a3b8; }}
.drivers li {{ margin: 2px 0; }}
.exec {{ color: #cbd5e1; font-size: 0.85rem; line-height: 1.55; }}
.map-wrap {{ margin-top: 8px; border: 1px solid var(--border); background: #0a1020; padding: 6px; }}
.feed-row {{ display: flex; align-items: center; gap: 8px; padding: 3px 0; }}
.feed-dot {{ width: 7px; height: 7px; border-radius: 50%; background: #64748b; flex-shrink: 0; }}
.feed-dot.ok {{ background: var(--green); box-shadow: 0 0 6px #22c55e88; }}
.feed-dot.mid {{ background: var(--yellow); box-shadow: 0 0 6px #eab30866; }}
.feed-dot.bad {{ background: var(--orange); }}
.footer {{ margin-top: 16px; color: var(--muted); font-size: 0.68rem; letter-spacing: 0.04em; }}
.stat-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0; }}
.stat {{
  background: #0a1020; border: 1px solid var(--border); padding: 6px 10px; min-width: 88px;
}}
.stat b {{ display: block; font-size: 1.1rem; color: var(--amber); }}
.stat span {{ color: var(--muted); font-size: 0.62rem; letter-spacing: 0.1em; text-transform: uppercase; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="banner {_risk_banner_class(word)}">
    <div>
      <div>GLOBAL RISK: {_esc(word)}</div>
      <div class="sub">{_esc(_trend_word(delta))} · {risk:.0f}/100 · {_esc('BASELINE' if first else 'DELTA')}</div>
    </div>
    <div class="sub" style="text-align:right">
      SHADOWBROKER SITREP<br/>{_esc(generated_at)}
    </div>
  </div>

  <div class="grid">
    <main>
      <section class="panel">
        <h2>Executive assessment</h2>
        <p class="exec">{_esc(exec_para)}</p>
        <div class="stat-row">
          <div class="stat"><b>{len(fps)}</b><span>Monitored</span></div>
          <div class="stat"><b>{sum(1 for f in fps if f.get('alert_level') in {'RED','BLACK'})}</b><span>Critical</span></div>
          <div class="stat"><b>{sum(1 for f in fps if float(f.get('det_delta') or 0) <= -3)}</b><span>Worsening</span></div>
          <div class="stat"><b>{sum(1 for f in fps if float(f.get('det_delta') or 0) >= 3)}</b><span>Improving</span></div>
          <div class="stat"><b>{sum(1 for f in fps if f.get('alert_level') == 'GREEN')}</b><span>Stable</span></div>
        </div>
      </section>

      <section class="panel" style="margin-top:12px">
        <h2>Theater map · hotspots</h2>
        <div class="map-wrap">{_html_world_map(fps)}</div>
        <div class="muted" style="margin-top:6px">Web Mercator basemap · hotspot color = alert band · callouts name each flashpoint.</div>
      </section>

      <section class="panel" style="margin-top:12px">
        <h2>Flashpoint watch · priority order</h2>
        {"".join(cards) if cards else '<div class="muted">No flashpoints</div>'}
      </section>

      <section class="panel" style="margin-top:12px">
        <h2>24-hour outlook</h2>
        {"".join(f'<div>{_esc(ln)}</div>' for ln in outlook_bits)}
      </section>
    </main>

    <aside class="side">
      <section class="panel">
        <h2>Top movers</h2>
        {movers_html}
      </section>
      <section class="panel">
        <h2>Emerging risks</h2>
        {emerging_html}
      </section>
      <section class="panel">
        <h2>Data feed health</h2>
        {feed_html}
      </section>
      <section class="panel">
        <h2>Domestic watch</h2>
        {"".join(
            f'<div class="mover"><span class="mover-name">{_esc(c.get("label"))}</span>'
            f'<span class="muted">{float(c.get("protest_potential") or 0):.0%}</span></div>'
            for c in (delta.get("us_cities") or [])[:5]
        ) or '<div class="muted">No elevated metros</div>'}
      </section>
    </aside>
  </div>

  <div class="footer">
    Self-hosted · Nash pure-strategy 2×2 · Deterrence = stability − GT risk − feed heat ·
    Confidence dots reflect feed density, not certainty of outcomes ·
    Compared to {_esc(delta.get("previous_generated_at") or "none")}
  </div>
</div>
</body></html>"""


def _try_pdf(html: str, path: Path) -> bool:
    try:
        from weasyprint import HTML  # type: ignore

        HTML(string=html).write_pdf(str(path))
        return True
    except Exception:
        pass
    try:
        import pdfkit  # type: ignore

        pdfkit.from_string(html, str(path))
        return True
    except Exception:
        return False


def _desktop_export_dir() -> Path | None:
    """
    Host-visible export folder for browsers (esp. Snap Firefox).

    Snap Firefox often cannot open multi-hop symlinks under ~/Shadowbroker.
    Writing real files under ~/Desktop/Daily_Inspiration avoids that.
    """
    raw = str(os.environ.get("DELTA_REPORT_DESKTOP_DIR", "")).strip()
    if raw:
        return Path(raw).expanduser()
    # Prefer host home when running as container user with /home/bob mounted
    for candidate in (
        Path.home() / "Desktop" / "Daily_Inspiration",
        Path("/home/bob/Desktop/Daily_Inspiration"),
    ):
        try:
            if candidate.parent.is_dir() or candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _write_export_copy(path: Path, content: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink()
        path.write_text(content, encoding="utf-8")
        try:
            path.chmod(0o644)
        except OSError:
            pass
        return True
    except OSError as exc:
        logger.warning("delta_report export write failed %s: %s", path, exc)
        return False


def _deliver_local(md: str, html: str, stamp: str) -> dict[str, str]:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _REPORT_DIR / f"delta_{stamp}.md"
    html_path = _REPORT_DIR / f"delta_{stamp}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    try:
        md_path.chmod(0o644)
        html_path.chmod(0o644)
    except OSError:
        pass

    # Real files (not symlinks) so file managers / Snap Firefox can open them
    latest_md = _REPORT_DIR / "latest.md"
    latest_html = _REPORT_DIR / "latest.html"
    _write_export_copy(latest_md, md)
    _write_export_copy(latest_html, html)

    paths: dict[str, str] = {"markdown": str(md_path), "html": str(html_path)}
    desk = _desktop_export_dir()
    if desk is not None:
        # Stable names on Desktop — real copies, no symlink hop
        desk_html = desk / "Shadowbroker_Strategic_Delta.html"
        desk_md = desk / "Shadowbroker_Strategic_Delta.md"
        if _write_export_copy(desk_html, html):
            paths["desktop_html"] = str(desk_html)
        if _write_export_copy(desk_md, md):
            paths["desktop_md"] = str(desk_md)
        # Also timestamped archive copy on Desktop (optional short name)
        stamp_html = desk / f"Shadowbroker_Delta_{stamp}.html"
        _write_export_copy(stamp_html, html)

    pdf_path = _REPORT_DIR / f"delta_{stamp}.pdf"
    if _try_pdf(html, pdf_path):
        paths["pdf"] = str(pdf_path)
    return paths


def _deliver_webhook(md: str, meta: dict[str, Any]) -> bool:
    url = str(os.environ.get("DELTA_REPORT_WEBHOOK_URL", "")).strip()
    if not url:
        return False
    # Prefer executive head for Discord limits
    head = "\n".join(md.splitlines()[:40])
    content = head[:1800] if "discord" in url.lower() else head[:8000]
    payload = json.dumps(
        {
            "content": content[:1900],
            "text": content,
            "username": "Shadowbroker Delta",
            "meta": meta,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Shadowbroker-DeltaReport/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("delta_report webhook failed: %s", exc)
        return False


def _deliver_smtp(md: str, subject: str) -> bool:
    host = str(os.environ.get("DELTA_REPORT_SMTP_HOST", "")).strip()
    to_addr = str(os.environ.get("DELTA_REPORT_SMTP_TO", "")).strip()
    if not host or not to_addr:
        return False
    port = _env_int("DELTA_REPORT_SMTP_PORT", 587)
    user = str(os.environ.get("DELTA_REPORT_SMTP_USER", "")).strip()
    password = str(os.environ.get("DELTA_REPORT_SMTP_PASSWORD", "")).strip()
    from_addr = str(os.environ.get("DELTA_REPORT_SMTP_FROM", "")).strip() or user or "shadowbroker@localhost"
    use_tls = _env_bool("DELTA_REPORT_SMTP_TLS", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(md, "plain", "utf-8"))
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("delta_report SMTP failed: %s", exc)
        return False


def generate_delta_report(
    *,
    force: bool = False,
    preview: bool = False,
    gt_risk: dict[str, Any] | None = None,
    telegram: dict[str, Any] | None = None,
    reddit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a delta brief. Skip write/send if no meaningful change (unless force/preview)."""
    global _last_run_iso, _last_report_meta

    if not delta_report_enabled() and not force and not preview:
        return {"enabled": False, "skipped": True, "reason": "disabled"}

    gt_risk, telegram, reddit = _snapshot_intel_layers(
        gt_risk=gt_risk, telegram=telegram, reddit=reddit
    )

    state = _load_state()
    previous = state.get("last_snapshot")
    delta = compute_deltas(
        gt_risk,
        previous if isinstance(previous, dict) else None,
        telegram=telegram,
        reddit=reddit,
    )

    if not force and not preview and not delta.get("has_meaningful_change"):
        return {
            "enabled": True,
            "skipped": True,
            "reason": "no_meaningful_change",
            "threshold": delta.get("threshold"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    generated_at = now.isoformat()
    md = render_markdown(delta, generated_at=generated_at)
    html = render_html_dashboard(
        delta, generated_at=generated_at, title=f"Strategic Delta SITREP {stamp}"
    )
    digest = hashlib.sha256(md.encode("utf-8")).hexdigest()[:16]
    summary = _exec_summary(delta)

    result: dict[str, Any] = {
        "enabled": True,
        "skipped": False,
        "preview": preview,
        "timestamp": generated_at,
        "stamp": stamp,
        "digest": digest,
        "markdown": md,
        "summary": summary,
        "top_region_shifts": delta.get("top_region_shifts"),
        "flashpoint_shifts": delta.get("flashpoint_shifts"),
        "has_meaningful_change": delta.get("has_meaningful_change"),
        "delivery": {},
    }

    if preview:
        return result

    paths = _deliver_local(md, html, stamp)
    result["delivery"]["local"] = paths
    result["delivery"]["webhook"] = _deliver_webhook(
        md, {"stamp": stamp, "digest": digest, "summary": summary}
    )
    result["delivery"]["smtp"] = _deliver_smtp(md, f"[Shadowbroker] Strategic Delta {stamp}")

    snapshot = {
        "regions": delta.get("regions"),
        "flashpoints": [
            {
                "id": f.get("id"),
                "nash_score": f.get("nash_score"),
                "deterrence": f.get("deterrence"),
                "keyword_hits": f.get("keyword_hits"),
            }
            for f in (delta.get("flashpoints_ranked") or [])
        ],
        "det_history": delta.get("det_history") or {},
        "generated_at": generated_at,
        "digest": digest,
        "paths": paths,
    }
    state["last_snapshot"] = snapshot
    state["last_report_at"] = generated_at
    state["last_paths"] = paths
    history = list(state.get("history") or [])
    history.append({"at": generated_at, "digest": digest, "paths": paths, "summary": summary})
    state["history"] = history[-30:]
    _save_state(state)

    with _lock:
        _last_run_iso = generated_at
        _last_report_meta = {
            "timestamp": generated_at,
            "digest": digest,
            "paths": paths,
            "summary": summary,
        }

    return result


def maybe_run_scheduled_delta_report(*, force_write: bool = True) -> dict[str, Any]:
    """
    Scheduler entry for the 6-hour SITREP.

    By default force_write=True so Markdown/HTML are always produced on schedule
    (even when risk deltas are small). Interval gating still prevents double-runs.
    """
    if not delta_report_enabled():
        return {"enabled": False, "skipped": True, "reason": "disabled"}

    state = _load_state()
    last = str(state.get("last_report_at") or "").strip()
    interval_h = delta_report_interval_hours()
    if last:
        try:
            prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - prev.astimezone(timezone.utc)).total_seconds() / 3600.0
            if age_h < interval_h:
                return {
                    "enabled": True,
                    "skipped": True,
                    "reason": "interval",
                    "age_hours": round(age_h, 2),
                    "interval_hours": interval_h,
                }
        except ValueError:
            pass

    # Always write files on the schedule so Desktop/NOC links stay fresh.
    return generate_delta_report(force=force_write, preview=False)


def list_recent_reports(limit: int = 10) -> list[dict[str, Any]]:
    state = _load_state()
    hist = list(state.get("history") or [])
    return list(reversed(hist[-max(1, limit) :]))


def get_last_report_meta() -> dict[str, Any] | None:
    with _lock:
        if _last_report_meta:
            return dict(_last_report_meta)
    state = _load_state()
    if state.get("last_report_at"):
        return {
            "timestamp": state.get("last_report_at"),
            "paths": state.get("last_paths"),
            "digest": (state.get("last_snapshot") or {}).get("digest"),
        }
    return None
