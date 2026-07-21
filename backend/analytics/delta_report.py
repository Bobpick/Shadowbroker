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


def sparkline(values: list[float], width: int = 8) -> str:
    """Tiny unicode sparkline from a series of 0–100 scores."""
    if not values:
        return "·" * width
    blocks = "▁▂▃▄▅▆▇█"
    series = values[-width:]
    lo, hi = min(series), max(series)
    span = hi - lo if hi > lo else 1.0
    out = []
    for v in series:
        idx = int(round((v - lo) / span * (len(blocks) - 1)))
        out.append(blocks[max(0, min(len(blocks) - 1, idx))])
    return "".join(out)


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

    strategic = build_strategic_analysis(gt_risk=gt_risk)
    prev_fp = {
        f.get("id"): f
        for f in ((previous_snapshot or {}).get("flashpoints") or [])
        if isinstance(f, dict)
    }
    # Historical series per flashpoint from prior snapshot
    history_map: dict[str, list[float]] = dict((previous_snapshot or {}).get("det_history") or {})

    enriched_fps: list[dict[str, Any]] = []
    fp_shifts: list[dict[str, Any]] = []
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
        series = series[-8:]
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
            "drivers": _fp_drivers(fp, old),
            "det_history": series,
            "sparkline": sparkline(series),
            "theater": _THEATER_MAP.get(pid, "Other"),
        }
        enriched_fps.append(row)
        if abs(det_delta) >= 5 or abs(nash_delta) >= 5 or not old or level in {"RED", "BLACK"}:
            fp_shifts.append(row)

    enriched_fps.sort(key=_flashpoint_priority_key)
    fp_shifts.sort(key=lambda f: float(f.get("det_delta") or 0))

    us_cities = (gt_risk or {}).get("us_cities") or {}
    cities = list(us_cities.get("cities") or [])[:8]

    has_signal = bool(shifts[:5] or fp_shifts or any(c.get("ignition") for c in shifts))
    first_run = not previous_snapshot

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
    }


# ── Briefing assembly ───────────────────────────────────────────────────────


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
        lines += [
            f"Priority {i}  ·  {f.get('label')}",
            "─" * 40,
            f"Alert:        {f.get('alert_level')} — {f.get('alert_label')}",
            f"Deterrence:   {prev:.0f} → {det:.0f}  {trend_arrows(d_det)}{abs(d_det):.0f}"
            if not delta.get("first_run")
            else f"Deterrence:   {det:.0f}  (baseline)",
            f"Nash:         {nash:.0f} ({f.get('nash_band')})  conf={f.get('confidence')}",
            f"Trend:        {f.get('sparkline')}  (recent cycles)",
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


def render_html(markdown_body: str, *, title: str) -> str:
    body = (
        markdown_body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background:#0b1220; color:#e2e8f0;
  padding:28px; max-width:920px; margin:auto; line-height:1.45; font-size:13px; }}
h1 {{ color:#fbbf24; font-size:1.35rem; letter-spacing:0.04em; }}
</style></head><body>
{body}
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


def _deliver_local(md: str, html: str, stamp: str) -> dict[str, str]:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _REPORT_DIR / f"delta_{stamp}.md"
    html_path = _REPORT_DIR / f"delta_{stamp}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    # Maintain latest.md for Desktop symlinks
    latest = _REPORT_DIR / "latest.md"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(md_path.name)
    except OSError:
        try:
            latest.write_text(md, encoding="utf-8")
        except OSError:
            pass
    paths = {"markdown": str(md_path), "html": str(html_path)}
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
) -> dict[str, Any]:
    """Build a delta brief. Skip write/send if no meaningful change (unless force/preview)."""
    global _last_run_iso, _last_report_meta

    if not delta_report_enabled() and not force and not preview:
        return {"enabled": False, "skipped": True, "reason": "disabled"}

    if gt_risk is None:
        try:
            from services.fetchers._store import latest_data

            gt_risk = dict(latest_data.get("gt_risk") or {})
        except Exception:
            gt_risk = {}

    state = _load_state()
    previous = state.get("last_snapshot")
    delta = compute_deltas(gt_risk, previous if isinstance(previous, dict) else None)

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
    html = render_html(md, title=f"Strategic Delta Brief {stamp}")
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


def maybe_run_scheduled_delta_report() -> dict[str, Any]:
    if not delta_report_enabled():
        return {"enabled": False, "skipped": True}

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

    return generate_delta_report(force=False, preview=False)


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
