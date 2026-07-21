"""Automated strategic delta reports — generate only when change is meaningful.

Produces Markdown (always) and simple HTML (for optional PDF tooling). Delivery:
local files, SMTP, webhook. Runs on a configurable interval (default 6h).
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
    # Default: on when GT is on
    try:
        from analytics.settings import gt_analytics_enabled

        return gt_analytics_enabled()
    except Exception:
        return False


def delta_report_interval_hours() -> int:
    return max(1, _env_int("DELTA_REPORT_INTERVAL_HOURS", 6))


def delta_threshold() -> float:
    """Minimum GT risk delta (absolute) to treat a region as meaningful."""
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

    # Strategic flashpoint changes
    from analytics.nash_deterrence import build_strategic_analysis

    strategic = build_strategic_analysis(gt_risk=gt_risk)
    prev_fp = {
        f.get("id"): f
        for f in ((previous_snapshot or {}).get("flashpoints") or [])
        if isinstance(f, dict)
    }
    fp_shifts: list[dict[str, Any]] = []
    for fp in strategic.get("flashpoints") or []:
        pid = fp.get("id")
        old = prev_fp.get(pid) or {}
        old_det = float((old.get("deterrence") or {}).get("score") or 50)
        new_det = float((fp.get("deterrence") or {}).get("score") or 50)
        old_nash = float(old.get("nash_score") or 50)
        new_nash = float(fp.get("nash_score") or 50)
        if abs(new_det - old_det) >= 5 or abs(new_nash - old_nash) >= 5 or not old:
            fp_shifts.append(
                {
                    "id": pid,
                    "label": fp.get("label"),
                    "deterrence": new_det,
                    "prev_deterrence": old_det,
                    "nash_score": new_nash,
                    "prev_nash": old_nash,
                    "band": (fp.get("deterrence") or {}).get("band"),
                    "nash_band": fp.get("nash_band"),
                }
            )

    us_cities = (gt_risk or {}).get("us_cities") or {}
    cities = list(us_cities.get("cities") or [])[:8]

    has_signal = bool(shifts[:5] or fp_shifts or any(c.get("ignition") for c in shifts))
    # First ever run always produces a baseline report
    first_run = not previous_snapshot

    return {
        "has_meaningful_change": has_signal or first_run,
        "first_run": first_run,
        "top_region_shifts": shifts[:8],
        "flashpoint_shifts": fp_shifts[:8],
        "us_cities": cities,
        "strategic": strategic,
        "regions": current,
        "threshold": threshold,
    }


def _exec_summary(delta: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for s in (delta.get("top_region_shifts") or [])[:5]:
        sign = "+" if float(s.get("delta") or 0) >= 0 else ""
        ign = " ⚡ignition" if s.get("ignition") else ""
        lines.append(
            f"{s.get('region')}: risk {float(s.get('prev_risk') or 0):.0%} → "
            f"{float(s.get('risk') or 0):.0%} ({sign}{float(s.get('delta') or 0):.0%}){ign}"
        )
    for f in (delta.get("flashpoint_shifts") or [])[:3]:
        lines.append(
            f"Flashpoint {f.get('label')}: deterrence "
            f"{float(f.get('prev_deterrence') or 0):.0f} → {float(f.get('deterrence') or 0):.0f} "
            f"(Nash {float(f.get('nash_score') or 0):.0f}, {f.get('band')})"
        )
    if not lines:
        lines.append("No region risk deltas above threshold; baseline snapshot only.")
    return lines[:5]


def render_markdown(delta: dict[str, Any], *, generated_at: str) -> str:
    summary = _exec_summary(delta)
    lines = [
        f"# Shadowbroker Strategic Delta Report",
        "",
        f"**Generated:** {generated_at}  ",
        f"**Threshold:** |Δrisk| ≥ {delta.get('threshold')}  ",
        f"**First run:** {delta.get('first_run')}",
        "",
        "## Executive summary",
        "",
    ]
    for i, s in enumerate(summary, 1):
        lines.append(f"{i}. {s}")
    lines += ["", "## Region risk shifts", ""]
    if not delta.get("top_region_shifts"):
        lines.append("_None above threshold._")
    else:
        lines.append("| Region | Prev | Now | Δ | Micro Δ | Ignition |")
        lines.append("|--------|------|-----|---|---------|----------|")
        for s in delta["top_region_shifts"]:
            lines.append(
                f"| {s.get('region')} | {float(s.get('prev_risk') or 0):.2f} | "
                f"{float(s.get('risk') or 0):.2f} | {float(s.get('delta') or 0):+.2f} | "
                f"{float(s.get('micro_delta') or 0):+.2f} | "
                f"{'yes' if s.get('ignition') else ''} |"
            )

    lines += ["", "## Nash / deterrence flashpoints", ""]
    fps = (delta.get("strategic") or {}).get("flashpoints") or []
    if not fps:
        lines.append("_Strategic analysis disabled or empty._")
    else:
        lines.append("| Flashpoint | Nash | Band | Deterrence | Det. band | Hits |")
        lines.append("|------------|------|------|------------|-----------|------|")
        for fp in fps[:12]:
            det = fp.get("deterrence") or {}
            lines.append(
                f"| {fp.get('label')} | {fp.get('nash_score')} | {fp.get('nash_band')} | "
                f"{det.get('score')} | {det.get('band')} | {fp.get('keyword_hits')} |"
            )

    lines += ["", "## US protest watch (active)", ""]
    cities = delta.get("us_cities") or []
    if not cities:
        lines.append("_No active US metros in snapshot._")
    else:
        for c in cities:
            lines.append(
                f"- **{c.get('label')}**: potential {float(c.get('protest_potential') or 0):.0%}, "
                f"unrest {float(c.get('unrest') or 0):.0%}, "
                f"protest hits {c.get('protest_mentions', 0)}"
            )

    lines += [
        "",
        "## Notes",
        "",
        "- Self-hosted analysis only; no external LLM required.",
        "- Nash scores are pure-strategy 2×2 equilibria fused with live GT risk.",
        "- Deterrence is an operational index, not formal proof of stability.",
        "",
    ]
    return "\n".join(lines)


def render_html(markdown_body: str, *, title: str) -> str:
    """Minimal HTML wrapper (print-to-PDF friendly)."""
    # Escape-light: we control markdown content
    body = (
        markdown_body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: ui-monospace, monospace; background:#0b1220; color:#e2e8f0; padding:24px; max-width:900px; margin:auto; }}
h1,h2 {{ color:#fbbf24; }}
</style></head><body>
{body}
</body></html>"""


def _try_pdf(html: str, path: Path) -> bool:
    """Optional PDF via weasyprint / pdfkit if installed; otherwise skip."""
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
    paths = {"markdown": str(md_path), "html": str(html_path)}
    pdf_path = _REPORT_DIR / f"delta_{stamp}.pdf"
    if _try_pdf(html, pdf_path):
        paths["pdf"] = str(pdf_path)
    return paths


def _deliver_webhook(md: str, meta: dict[str, Any]) -> bool:
    url = str(os.environ.get("DELTA_REPORT_WEBHOOK_URL", "")).strip()
    if not url:
        return False
    # Discord-friendly content field (truncate)
    content = md[:1800] if "discord" in url.lower() else md[:8000]
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
    """
    Build a delta report. If not force and no meaningful change, skip write/send.
    preview=True never delivers and does not update state.
    """
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
    html = render_html(md, title=f"Delta Report {stamp}")
    digest = hashlib.sha256(md.encode("utf-8")).hexdigest()[:16]

    result: dict[str, Any] = {
        "enabled": True,
        "skipped": False,
        "preview": preview,
        "timestamp": generated_at,
        "stamp": stamp,
        "digest": digest,
        "markdown": md,
        "summary": _exec_summary(delta),
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
        md, {"stamp": stamp, "digest": digest, "summary": result["summary"]}
    )
    result["delivery"]["smtp"] = _deliver_smtp(md, f"[Shadowbroker] Strategic Delta {stamp}")

    # Update state for next comparison
    snapshot = {
        "regions": delta.get("regions"),
        "flashpoints": [
            {
                "id": f.get("id"),
                "nash_score": f.get("nash_score"),
                "deterrence": f.get("deterrence"),
            }
            for f in ((delta.get("strategic") or {}).get("flashpoints") or [])
        ],
        "generated_at": generated_at,
        "digest": digest,
        "paths": paths,
    }
    state["last_snapshot"] = snapshot
    state["last_report_at"] = generated_at
    state["last_paths"] = paths
    history = list(state.get("history") or [])
    history.append({"at": generated_at, "digest": digest, "paths": paths})
    state["history"] = history[-30:]
    _save_state(state)

    with _lock:
        _last_run_iso = generated_at
        _last_report_meta = {
            "timestamp": generated_at,
            "digest": digest,
            "paths": paths,
            "summary": result["summary"],
        }

    return result


def maybe_run_scheduled_delta_report() -> dict[str, Any]:
    """Scheduler entry — honor interval and skip empty deltas."""
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
