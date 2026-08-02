#!/usr/bin/env python3
"""PAT Labs weekly intel pack — past 7 days for group intel meetings.

Reads the rolling history JSON filled by daily_24h_brief.py, optionally
refreshes live feeds for context, writes fixed-name MD + email HTML:

  ~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.md
  ~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.html

No dated archive copies. Uses Ollama (default cogito:32b) for narrative.
Weekly product is an issues synopsis for intel meetings — not tasking.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

# Reuse daily brief helpers
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import daily_24h_brief as daily  # noqa: E402

WEEK_DAYS = max(1, int(os.environ.get("WEEKLY_BRIEF_DAYS", "7") or "7"))
OUT_DIR = daily.OUT_DIR
OUT_MD = OUT_DIR / "pat_labs_weekly_intel.md"
OUT_HTML = OUT_DIR / "pat_labs_weekly_intel.html"
OLLAMA_MODEL = os.environ.get("WEEKLY_BRIEF_OLLAMA_MODEL") or daily.OLLAMA_MODEL


def _now() -> datetime:
    return datetime.now().astimezone()


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def slice_week(doc: dict[str, Any], *, days: int = WEEK_DAYS) -> list[dict[str, Any]]:
    rows = [d for d in (doc.get("days") or []) if isinstance(d, dict) and d.get("date")]
    rows.sort(key=lambda d: str(d.get("date") or ""))
    if not rows:
        return []
    # Prefer calendar last N days ending at latest snapshot
    try:
        end = datetime.fromisoformat(str(rows[-1]["date"])).date()
    except ValueError:
        return rows[-days:]
    start = end - timedelta(days=days - 1)
    window = []
    for d in rows:
        try:
            dd = datetime.fromisoformat(str(d["date"])).date()
        except ValueError:
            continue
        if start <= dd <= end:
            window.append(d)
    return window or rows[-days:]


def week_metrics(days: list[dict[str, Any]]) -> dict[str, Any]:
    if not days:
        return {
            "days_available": 0,
            "date_start": None,
            "date_end": None,
            "platform_scores": [],
            "strategic_scores": [],
            "pathogen_counts": [],
            "flight_counts": [],
            "priority_frequency": {},
            "pathogen_frequency": {},
            "score_trail": [],
            "changes": [],
            "headline_leads": {"domestic": [], "foreign": []},
        }

    platform_scores: list[tuple[str, float | None]] = []
    strategic_scores: list[tuple[str, float | None]] = []
    pathogen_counts: list[tuple[str, float | None]] = []
    flight_counts: list[tuple[str, float | None]] = []
    pri_freq: dict[str, int] = {}
    path_freq: dict[str, int] = {}
    score_trail: list[str] = []
    dom_heads: list[str] = []
    for_heads: list[str] = []

    def _f(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    for d in days:
        date = str(d.get("date") or "")
        pt = d.get("platform_threat") or {}
        st = d.get("strategic") or {}
        met = d.get("metrics") or {}
        ps, ss = _f(pt.get("score")), _f(st.get("overall_risk_score"))
        pr, fl = _f(met.get("pathogens_rising")), _f(met.get("military_flights"))
        platform_scores.append((date, ps))
        strategic_scores.append((date, ss))
        pathogen_counts.append((date, pr))
        flight_counts.append((date, fl))
        score_trail.append(
            f"{date}: platform {pt.get('score')}/{pt.get('level')}"
            + (
                f", strategic {st.get('overall_risk_score')}/{st.get('overall_risk_word')}"
                if st.get("overall_risk_score") is not None or st.get("overall_risk_word")
                else ""
            )
        )
        for p in st.get("priorities") or []:
            if isinstance(p, dict) and p.get("region"):
                name = str(p["region"]).strip()
                pri_freq[name] = pri_freq.get(name, 0) + 1
        for p in d.get("pathogens_rising") or []:
            if isinstance(p, dict) and p.get("name"):
                name = str(p["name"]).strip()
                path_freq[name] = path_freq.get(name, 0) + 1
        hl = d.get("headline_leads") or {}
        for t in (hl.get("domestic") or [])[:3]:
            if t and t not in dom_heads:
                dom_heads.append(str(t))
        for t in (hl.get("foreign") or [])[:3]:
            if t and t not in for_heads:
                for_heads.append(str(t))

    def _series_delta(series: list[tuple[str, float | None]]) -> dict[str, Any] | None:
        nums = [(d, v) for d, v in series if v is not None]
        if len(nums) < 2:
            return None
        a, b = nums[0][1], nums[-1][1]
        assert a is not None and b is not None
        return {
            "from_date": nums[0][0],
            "to_date": nums[-1][0],
            "from": a,
            "to": b,
            "delta": b - a,
            "direction": "up" if b > a else ("down" if b < a else "flat"),
        }

    changes = []
    for key, series, label in (
        ("platform_score", platform_scores, "Platform threat score"),
        ("strategic_score", strategic_scores, "Strategic risk score"),
        ("pathogens_rising", pathogen_counts, "Pathogens rising (count)"),
        ("military_flights", flight_counts, "Military flights tracked"),
    ):
        dlt = _series_delta(series)
        if dlt:
            changes.append({"metric": key, "label": label, **dlt})

    top_priorities = sorted(pri_freq.items(), key=lambda x: (-x[1], x[0]))[:8]
    top_pathogens = sorted(path_freq.items(), key=lambda x: (-x[1], x[0]))[:8]

    return {
        "days_available": len(days),
        "date_start": days[0].get("date"),
        "date_end": days[-1].get("date"),
        "platform_scores": platform_scores,
        "strategic_scores": strategic_scores,
        "pathogen_counts": pathogen_counts,
        "flight_counts": flight_counts,
        "priority_frequency": dict(top_priorities),
        "pathogen_frequency": dict(top_pathogens),
        "score_trail": score_trail,
        "changes": changes,
        "headline_leads": {
            "domestic": dom_heads[:12],
            "foreign": for_heads[:12],
        },
        "days": days,
    }


def ollama_weekly(metrics: dict[str, Any], live: dict[str, Any] | None) -> dict[str, str]:
    """Narrative for a weekly issues synopsis (no tasking)."""
    pack = {
        "window": {
            "start": metrics.get("date_start"),
            "end": metrics.get("date_end"),
            "days_available": metrics.get("days_available"),
        },
        "score_trail": metrics.get("score_trail"),
        "changes": metrics.get("changes"),
        "priority_frequency": metrics.get("priority_frequency"),
        "pathogen_frequency": metrics.get("pathogen_frequency"),
        "headline_leads": metrics.get("headline_leads"),
        "live_threat": (live or {}).get("threat_level"),
        "live_wastewater_rising": ((live or {}).get("wastewater") or {}).get("rising"),
    }
    pack_json = json.dumps(pack, ensure_ascii=False, indent=2)
    system = (
        "You write weekly intelligence synopses for professionals. "
        "Sum up what happened and which issues mattered. "
        "Do NOT assign tasks, owners, discussion questions, or action items. "
        "Use ONLY provided facts. No medical advice, no panic. "
        "In the first paragraph only, mention once that platform/strategic scores "
        "are 0–100 risk scales (higher = worse). Do not repeat that explanation later. "
        "Plain prose only — no markdown headings, no bullet outlines, "
        "no 'Based on the provided data'."
    )
    overview_user = f"""Write the Weekly Issues Synopsis for the past week.

Exactly 3–4 continuous paragraphs of plain English (about 280–500 words).
Cover: how risk moved; which theaters dominated; biosecurity/pathogen issues;
major news themes; residual issues still open at week end.
State the score scale once in paragraph 1 only (0–100, higher = worse), then do not re-explain it.
Do NOT invent events. Do NOT assign work or ask discussion questions.

Facts:
{pack_json}
"""
    issues_user = f"""Return JSON only (no fences) with exactly these keys:
- "top_issues": array of 5–8 short issue statements (what happened / why it mattered), grounded in facts. Not tasks.
- "theater_issues": array of 3–6 theater/region issue lines (name + what deteriorated or improved).
- "biosecurity_issues": array of 2–5 pathogen/public-health surveillance issue lines from the data.
- "closing_issues": array of 3–5 residual issues still open at week end (watch items as issues, not assignments).

Facts:
{pack_json}
"""
    old = daily.OLLAMA_MODEL
    daily.OLLAMA_MODEL = OLLAMA_MODEL
    try:
        overview = daily._clean_exec_prose(
            daily._ollama_chat(system, overview_user, num_predict=2400)
        )
        if not daily._exec_prose_ok(overview):
            overview = daily._clean_exec_prose(
                daily._ollama_chat(
                    system,
                    "Rewrite as 3–4 plain paragraphs only. Zero markdown. "
                    "Mention score scale once only.\n\n" + pack_json,
                    num_predict=2000,
                )
            )
        support = daily._parse_json_object(
            daily._ollama_chat(system, issues_user, num_predict=1400)
        ) or {}
    finally:
        daily.OLLAMA_MODEL = old

    def _arr(key: str) -> list[str]:
        v = support.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return daily._normalize_watch_items(v)
        return []

    return {
        "overview": overview if daily._exec_prose_ok(overview) else "",
        "top_issues": _arr("top_issues"),
        "theater_issues": _arr("theater_issues"),
        "biosecurity_issues": _arr("biosecurity_issues"),
        "closing_issues": _arr("closing_issues"),
    }


def fallback_overview(metrics: dict[str, Any]) -> str:
    if not metrics.get("days_available"):
        return (
            "No daily history is available yet. After several morning PAT Labs briefs, "
            "this weekly synopsis will summarize the week’s issues, score movement, "
            "priority theaters, and biosecurity signals. Higher platform and strategic "
            "scores mean higher risk (worse), not better."
        )
    trail = "; ".join(metrics.get("score_trail") or [])
    changes = metrics.get("changes") or []
    ch_txt = []
    for c in changes:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        ch_txt.append(
            f"{c.get('label')}: {c.get('from'):g} → {c.get('to'):g} "
            f"({arrow}{abs(float(c.get('delta') or 0)):g})"
        )
    pris = ", ".join(f"{k} ({v}d)" for k, v in (metrics.get("priority_frequency") or {}).items())
    paths = ", ".join(f"{k} ({v}d)" for k, v in (metrics.get("pathogen_frequency") or {}).items())
    p1 = (
        f"This weekly synopsis covers {metrics.get('date_start')} through {metrics.get('date_end')} "
        f"({metrics.get('days_available')} daily snapshots). "
        f"Platform and strategic scores use a 0–100 risk scale (higher = worse, lower = better). "
        f"Score trail: {trail}."
    )
    p2 = (
        "Week movement: " + ("; ".join(ch_txt) if ch_txt else "insufficient paired scores for deltas.")
        + f" Theaters most often on priority watch: {pris or 'n/a'}."
    )
    p3 = (
        f"Pathogens most often marked rising: {paths or 'n/a'}. "
        "The list below restates the week’s dominant issues for the intel meeting; "
        "confirm with the latest daily brief and strategic delta SITREP."
    )
    return f"{p1}\n\n{p2}\n\n{p3}"


def _issue_list_from_metrics(metrics: dict[str, Any]) -> dict[str, list[str]]:
    """Structured issues when the model is offline."""
    top: list[str] = []
    for c in metrics.get("changes") or []:
        arrow = "rose" if c.get("direction") == "up" else (
            "fell" if c.get("direction") == "down" else "held"
        )
        top.append(
            f"{c.get('label')} {arrow} from {c.get('from'):g} to {c.get('to'):g} "
            f"over {c.get('from_date')}–{c.get('to_date')}."
        )
    theaters = [
        f"{name} appeared on priority watch {count} day(s) this week."
        for name, count in (metrics.get("priority_frequency") or {}).items()
    ]
    bio = [
        f"{name} was marked rising on {count} day(s) in wastewater surveillance."
        for name, count in (metrics.get("pathogen_frequency") or {}).items()
    ]
    closing = theaters[:3] + bio[:2]
    if not closing:
        closing = ["Insufficient history to name residual open issues."]
    # Headlines as issues
    for t in ((metrics.get("headline_leads") or {}).get("domestic") or [])[:2]:
        top.append(f"Domestic lead theme: {t}")
    for t in ((metrics.get("headline_leads") or {}).get("foreign") or [])[:2]:
        top.append(f"International lead theme: {t}")
    return {
        "top_issues": top[:8] or ["No scored issues yet — need more daily snapshots."],
        "theater_issues": theaters[:6] or ["No theater priority history in window."],
        "biosecurity_issues": bio[:5] or ["No rising-pathogen history in window."],
        "closing_issues": closing[:5],
    }


def build_markdown(metrics: dict[str, Any], prose: dict[str, str], live: dict[str, Any] | None) -> str:
    when = _now().isoformat(timespec="seconds")
    overview = (prose.get("overview") or "").strip() or fallback_overview(metrics)
    fb = _issue_list_from_metrics(metrics)

    def issues(key: str) -> list[str]:
        raw = prose.get(key) or []
        if isinstance(raw, str):
            raw = daily._normalize_watch_items(raw)
        return list(raw)[:8] if raw else list(fb.get(key) or [])

    lines = [
        "# PAT Labs — Weekly Issues Synopsis",
        "",
        f"**Generated:** {when}  ",
        f"**Window:** {metrics.get('date_start') or '—'} → {metrics.get('date_end') or '—'} "
        f"({metrics.get('days_available') or 0} daily snapshots)  ",
        f"**Audience:** Weekly intel meeting  ",
        "",
        "---",
        "",
        "## Week in Brief",
        "",
        overview,
        "",
        "## Scoreboard",
        "",
        "| Date | Platform threat | Strategic risk | Pathogens rising | Mil. flights |",
        "|---|---|---|---:|---:|",
    ]
    for d in metrics.get("days") or []:
        pt = d.get("platform_threat") or {}
        st = d.get("strategic") or {}
        met = d.get("metrics") or {}
        lines.append(
            f"| {d.get('date')} | {pt.get('score')}/{pt.get('level')} | "
            f"{st.get('overall_risk_score')}/{st.get('overall_risk_word')} | "
            f"{met.get('pathogens_rising')} | {met.get('military_flights')} |"
        )

    lines += ["", "## How Risk Moved", ""]
    for c in metrics.get("changes") or []:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        lines.append(
            f"- **{c.get('label')}:** {c.get('from'):g} → {c.get('to'):g} "
            f"({arrow}{abs(float(c.get('delta') or 0)):g}) "
            f"[{c.get('from_date')} → {c.get('to_date')}]"
        )
    if not metrics.get("changes"):
        lines.append("- Not enough multi-day points yet for week-over-week deltas.")

    lines += ["", "## Top Issues This Week", ""]
    for i, it in enumerate(issues("top_issues"), 1):
        lines.append(f"{i}. {it}")

    lines += ["", "## Theater & Strategic Issues", ""]
    for it in issues("theater_issues"):
        lines.append(f"- {it}")

    lines += ["", "## Biosecurity Issues", ""]
    for it in issues("biosecurity_issues"):
        lines.append(f"- {it}")

    lines += ["", "## Headline Themes Captured", "", "### Domestic", ""]
    for t in (metrics.get("headline_leads") or {}).get("domestic") or []:
        lines.append(f"- {t}")
    if not (metrics.get("headline_leads") or {}).get("domestic"):
        lines.append("- None stored in daily history.")
    lines += ["", "### International", ""]
    for t in (metrics.get("headline_leads") or {}).get("foreign") or []:
        lines.append(f"- {t}")
    if not (metrics.get("headline_leads") or {}).get("foreign"):
        lines.append("- None stored in daily history.")

    lines += ["", "## Issues Still Open at Week End", ""]
    for it in issues("closing_issues"):
        lines.append(f"- {it}")

    if live and isinstance(live.get("threat_level"), dict):
        tl = live["threat_level"]
        lines += [
            "",
            "## Live Snapshot When This Pack Was Built",
            "",
            f"- Platform threat: **{tl.get('level')}** ({tl.get('score')}/100)",
        ]
        for dr in (tl.get("drivers") or [])[:5]:
            lines.append(f"- {dr}")

    lines += [
        "",
        "---",
        "",
        "## Methodology",
        "",
        "Summation of daily PAT Labs snapshots for the last week. "
        f"History file retention ~{daily.HISTORY_DAYS} days; weekly window = last {WEEK_DAYS} "
        "calendar days present. Open-source only; wastewater sampling lags. "
        "Meeting synopsis of issues — not tasking and not medical advice.",
        "",
        f"_History file: `{daily.HISTORY_JSON}`_",
        "",
    ]
    return "\n".join(lines)


def render_weekly_html(md: str, metrics: dict[str, Any]) -> str:
    """Email-safe weekly issues synopsis (no tasking)."""
    title_start = metrics.get("date_start") or "—"
    title_end = metrics.get("date_end") or "—"
    title = f"PAT Labs Weekly Issues — {title_start} to {title_end}"
    gen = _now().strftime("%Y-%m-%d %H:%M %Z")

    def esc(s: Any) -> str:
        return html.escape("" if s is None else str(s))

    def section_body(heading: str) -> str:
        return daily._md_section_body(md, heading)

    def paras_html(text: str) -> str:
        text = daily._clean_exec_prose(text) if text else ""
        out = []
        for p in re.split(r"\n\s*\n", text):
            p = p.strip()
            if not p:
                continue
            p = re.sub(r"^#{1,6}\s+", "", p)
            p = re.sub(r"\*\*(.+?)\*\*", r"\1", p)
            out.append(
                f'<p style="margin:0 0 12px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
                f'font-size:14px;color:#0f172a;line-height:1.55;">{esc(p)}</p>'
            )
        return "\n".join(out)

    def bullets_html(text: str, *, numbered: bool = False) -> str:
        items = daily._md_bullets(text)
        if not items:
            for line in text.splitlines():
                m = re.match(r"^\d+\.\s+(.+)$", line.strip())
                if m:
                    items.append(m.group(1).strip())
        if not items and text.strip() and "None stored" not in text:
            # keep explicit "none" lines
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("- "):
                    items.append(s[2:])
                elif s and not s.startswith("#"):
                    items.append(s)
        rows = []
        for i, it in enumerate(items, 1):
            mark = f"{i}." if numbered else "•"
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", it)
            rows.append(
                f'<tr><td width="22" valign="top" style="padding:6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
                f'font-size:13px;color:#1e3a5f;font-weight:700;">{mark}</td>'
                f'<td style="padding:6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;'
                f'color:#1e293b;line-height:1.45;">{esc(clean)}</td></tr>'
            )
        if not rows:
            rows.append(
                '<tr><td style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">'
                "No items in window.</td></tr>"
            )
        return (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{"".join(rows)}</table>'
        )

    mrows = ""
    for d in metrics.get("days") or []:
        pt = d.get("platform_threat") or {}
        st = d.get("strategic") or {}
        met = d.get("metrics") or {}
        plat = f"{pt.get('score')}/{pt.get('level')}"
        strat = f"{st.get('overall_risk_score')}/{st.get('overall_risk_word')}"
        mrows += (
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(d.get("date"))}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;font-weight:700;">{esc(plat)}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(strat)}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(met.get("pathogens_rising") if met.get("pathogens_rising") is not None else "—")}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(met.get("military_flights") if met.get("military_flights") is not None else "—")}</td>'
            "</tr>"
        )

    movement = ""
    for c in metrics.get("changes") or []:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        color = "#0f172a"
        if c.get("metric") in {"platform_score", "strategic_score", "pathogens_rising"}:
            if c.get("direction") == "up":
                color = "#b91c1c"
            elif c.get("direction") == "down":
                color = "#047857"
        movement += (
            f'<tr><td width="18" valign="top" style="padding:5px 0;color:#94a3b8;">•</td>'
            f'<td style="padding:5px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:{color};">'
            f'<strong>{esc(c.get("label"))}:</strong> {esc(c.get("from"))} → {esc(c.get("to"))} '
            f'({arrow}{esc(abs(float(c.get("delta") or 0)))})</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:#e8eef4;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    Weekly issues synopsis {esc(title_start)} to {esc(title_end)}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#e8eef4;">
    <tr><td align="center" style="padding:20px 12px;">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background:#ffffff;border:1px solid #d0d7de;">

        <tr><td style="background:#0b1f33;padding:20px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">
            PAT Labs · Weekly Issues Synopsis
          </div>
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;color:#ffffff;margin-top:6px;">
            Last Week&rsquo;s Issues
          </div>
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#8ba3b7;margin-top:6px;">
            {esc(title_start)} → {esc(title_end)} · {esc(metrics.get("days_available"))} daily snapshots · Generated {esc(gen)}
          </div>
        </td></tr>

        <tr><td style="padding:22px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:12px;">
            Week in Brief
          </div>
          {paras_html(section_body("Week in Brief"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:10px;">
            Scoreboard
          </div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e2e8f0;">
            <tr style="background:#f8fafc;">
              <th align="left" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Date</th>
              <th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Platform</th>
              <th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Strategic</th>
              <th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Path ↑</th>
              <th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Flights</th>
            </tr>
            {mrows or '<tr><td colspan="5" style="padding:12px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#64748b;">No daily snapshots in window.</td></tr>'}
          </table>
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            How Risk Moved
          </div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            {movement or '<tr><td style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">Insufficient multi-day data.</td></tr>'}
          </table>
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Top Issues This Week
          </div>
          {bullets_html(section_body("Top Issues This Week"), numbered=True)}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Theater &amp; Strategic Issues
          </div>
          {bullets_html(section_body("Theater & Strategic Issues"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Biosecurity Issues
          </div>
          {bullets_html(section_body("Biosecurity Issues"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Headline Themes
          </div>
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;color:#64748b;margin:8px 0 4px;">Domestic</div>
          {bullets_html(section_body("Headline Themes Captured").split("### International")[0] if "### International" in section_body("Headline Themes Captured") else section_body("Headline Themes Captured"))}
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;color:#64748b;margin:12px 0 4px;">International</div>
          {bullets_html("### International" + section_body("Headline Themes Captured").split("### International", 1)[-1] if "### International" in section_body("Headline Themes Captured") else "")}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Issues Still Open at Week End
          </div>
          {bullets_html(section_body("Issues Still Open at Week End"))}
        </td></tr>

        <tr><td style="padding:20px 24px 24px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:14px;margin-bottom:8px;">
            Methodology
          </div>
          <p style="margin:0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#94a3b8;line-height:1.5;">
            Summation of the week&rsquo;s issues from daily PAT Labs snapshots.
            Open-source feeds; wastewater sampling lags. Synopsis only — not tasking, not medical advice.
          </p>
          <p style="margin:12px 0 0 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#cbd5e1;letter-spacing:0.06em;text-transform:uppercase;">
            PAT Labs · Weekly Issues Synopsis
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def send_email(html_doc: str, md: str, subject: str) -> bool:
    host = _env("WEEKLY_BRIEF_SMTP_HOST") or _env("DAILY_BRIEF_SMTP_HOST") or _env("DELTA_REPORT_SMTP_HOST")
    to_addr = _env("WEEKLY_BRIEF_SMTP_TO") or _env("DAILY_BRIEF_SMTP_TO") or _env("DELTA_REPORT_SMTP_TO")
    if not host or not to_addr:
        return False
    port = int(_env("WEEKLY_BRIEF_SMTP_PORT") or _env("DAILY_BRIEF_SMTP_PORT") or _env("DELTA_REPORT_SMTP_PORT") or "587")
    user = _env("WEEKLY_BRIEF_SMTP_USER") or _env("DAILY_BRIEF_SMTP_USER") or _env("DELTA_REPORT_SMTP_USER")
    password = _env("WEEKLY_BRIEF_SMTP_PASSWORD") or _env("DAILY_BRIEF_SMTP_PASSWORD") or _env("DELTA_REPORT_SMTP_PASSWORD")
    from_addr = (
        _env("WEEKLY_BRIEF_SMTP_FROM")
        or _env("DAILY_BRIEF_SMTP_FROM")
        or _env("DELTA_REPORT_SMTP_FROM")
        or user
        or "patlabs@localhost"
    )
    use_tls = _env_bool("WEEKLY_BRIEF_SMTP_TLS", True)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(md, "plain", "utf-8"))
    msg.attach(MIMEText(html_doc, "html", "utf-8"))
    recipients = [a.strip() for a in to_addr.split(",") if a.strip()]
    try:
        with smtplib.SMTP(host, port, timeout=45) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, recipients, msg.as_string())
        print(f"[ok] email sent to {to_addr}")
        return True
    except Exception as exc:
        print(f"[warn] SMTP failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="PAT Labs weekly intel meeting pack")
    parser.add_argument("--no-ollama", action="store_true")
    parser.add_argument("--no-live", action="store_true", help="Skip live Shadowbroker pull")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--days", type=int, default=WEEK_DAYS, help="Days in window (default 7)")
    args = parser.parse_args()

    days_n = max(1, int(args.days or WEEK_DAYS))
    print(f"[info] loading history {daily.HISTORY_JSON} …")
    hist = daily.load_history()
    week_days = slice_week(hist, days=days_n)
    metrics = week_metrics(week_days)
    print(
        f"[info] window {metrics.get('date_start')} → {metrics.get('date_end')} "
        f"({metrics.get('days_available')} days)"
    )

    live: dict[str, Any] | None = None
    if not args.no_live:
        try:
            print(f"[info] live snapshot from {daily.SB_BASE} …")
            live = daily.collect_context()
        except Exception as exc:
            print(f"[warn] live collect failed: {exc}", file=sys.stderr)

    prose: dict[str, str] = {}
    if not args.no_ollama:
        print(f"[info] Ollama model={OLLAMA_MODEL} …")
        prose = ollama_weekly(metrics, live)
        if prose.get("overview"):
            print(f"[info] weekly overview ~{len(prose['overview'].split())} words")
        else:
            print("[warn] overview empty — using structured fallback", file=sys.stderr)

    md = build_markdown(metrics, prose, live)
    html_doc = render_weekly_html(md, metrics)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    try:
        OUT_MD.chmod(0o644)
        OUT_HTML.chmod(0o644)
    except OSError:
        pass
    print(f"[ok] wrote {OUT_MD}")
    print(f"[ok] wrote {OUT_HTML}")

    want_email = args.email or (not args.no_email and _env_bool("WEEKLY_BRIEF_EMAIL", False))
    if want_email:
        send_email(
            html_doc,
            md,
            subject=f"[PAT Labs] Weekly Intel Pack — {metrics.get('date_start')} to {metrics.get('date_end')}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
