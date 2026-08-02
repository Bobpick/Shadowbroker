#!/usr/bin/env python3
"""PAT Labs weekly intel pack — past 7 days for group intel meetings.

Reads the rolling history JSON filled by daily_24h_brief.py, optionally
refreshes live feeds for context, writes fixed-name MD + email HTML:

  ~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.md
  ~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.html

No dated archive copies. Uses Ollama (default cogito:14b) for narrative.
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
        "You write weekly intelligence meeting packs for professional analysts. "
        "Plain prose only. Use ONLY provided facts. No medical advice, no panic, "
        "no markdown headings, no bullet outlines, no 'Based on the provided data'."
    )
    sit_user = f"""Write the Weekly Situation Overview for a 45-minute intel meeting.

Requirements:
- Exactly 3 paragraphs of plain English (about 250–450 words total).
- Cover: week-over-week risk movement, which theaters dominated the week, biosecurity (pathogens that appeared most often), and what the meeting should prioritize next week.
- No markdown. No section titles. No lists.

Facts:
{pack_json}
"""
    discussion_user = f"""Return JSON only (no fences) with keys:
- "discussion_questions": array of 5 short questions for the group (grounded in facts).
- "watch_next_week": array of 5–7 concrete watch items for the coming week.
- "decision_points": array of 3 optional decision/check items (monitoring only if no action data).

Facts:
{pack_json}
"""
    # Use weekly model override via env already on daily.OLLAMA_MODEL if set before import — patch
    old = daily.OLLAMA_MODEL
    daily.OLLAMA_MODEL = OLLAMA_MODEL
    try:
        overview = daily._clean_exec_prose(daily._ollama_chat(system, sit_user, num_predict=2200))
        if not daily._exec_prose_ok(overview):
            overview = daily._clean_exec_prose(
                daily._ollama_chat(
                    system,
                    "Rewrite as THREE plain paragraphs only. Zero markdown.\n\n" + pack_json,
                    num_predict=1800,
                )
            )
        support = daily._parse_json_object(
            daily._ollama_chat(system, discussion_user, num_predict=1200)
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
        "discussion_questions": _arr("discussion_questions"),
        "watch_next_week": _arr("watch_next_week"),
        "decision_points": _arr("decision_points"),
    }


def fallback_overview(metrics: dict[str, Any]) -> str:
    if not metrics.get("days_available"):
        return (
            "No daily history is available yet. Run the morning PAT Labs brief for several days "
            "so this weekly pack can summarize progression. Until then, treat live Shadowbroker "
            "feeds and the latest strategic delta as the primary source for the meeting."
        )
    trail = "; ".join(metrics.get("score_trail") or [])
    changes = metrics.get("changes") or []
    ch_txt = []
    for c in changes:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        ch_txt.append(
            f"{c.get('label')}: {c.get('from'):g} → {c.get('to'):g} ({arrow}{abs(float(c.get('delta') or 0)):g})"
        )
    pris = ", ".join(f"{k} ({v}d)" for k, v in (metrics.get("priority_frequency") or {}).items())
    paths = ", ".join(f"{k} ({v}d)" for k, v in (metrics.get("pathogen_frequency") or {}).items())
    p1 = (
        f"This weekly pack covers {metrics.get('date_start')} through {metrics.get('date_end')} "
        f"({metrics.get('days_available')} daily snapshots). Score trail: {trail}."
    )
    p2 = (
        "Week movement: " + ("; ".join(ch_txt) if ch_txt else "insufficient paired scores for deltas.")
        + f" Theaters most often on priority watch: {pris or 'n/a'}."
    )
    p3 = (
        f"Pathogens most often marked rising: {paths or 'n/a'}. "
        "Use Priority Watch frequency and score movement to set the meeting agenda; "
        "confirm with the latest daily HTML brief and strategic delta SITREP."
    )
    return f"{p1}\n\n{p2}\n\n{p3}"


def build_markdown(metrics: dict[str, Any], prose: dict[str, str], live: dict[str, Any] | None) -> str:
    when = _now().isoformat(timespec="seconds")
    overview = (prose.get("overview") or "").strip() or fallback_overview(metrics)
    lines = [
        "# PAT Labs — Weekly Intelligence Pack",
        "",
        f"**Generated:** {when}  ",
        f"**Window:** {metrics.get('date_start') or '—'} → {metrics.get('date_end') or '—'} "
        f"({metrics.get('days_available') or 0} daily snapshots)  ",
        f"**Audience:** Weekly intel meeting  ",
        "",
        "---",
        "",
        "## Situation Overview",
        "",
        overview,
        "",
        "## Week-at-a-Glance Metrics",
        "",
        "| Date | Platform | Strategic | Pathogens ↑ | Mil. flights |",
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

    lines += ["", "## Score Movement (first → last day in window)", ""]
    for c in metrics.get("changes") or []:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        lines.append(
            f"- **{c.get('label')}:** {c.get('from'):g} → {c.get('to'):g} "
            f"({arrow}{abs(float(c.get('delta') or 0)):g}) "
            f"[{c.get('from_date')} → {c.get('to_date')}]"
        )
    if not metrics.get("changes"):
        lines.append("- Not enough multi-day points yet for deltas.")

    lines += ["", "## Theaters Most Often on Priority Watch", ""]
    for name, count in (metrics.get("priority_frequency") or {}).items():
        lines.append(f"- **{name}** — {count} day(s) in top priorities")
    if not metrics.get("priority_frequency"):
        lines.append("- No priority theater history in window.")

    lines += ["", "## Biosecurity — Pathogens Most Often Rising", ""]
    for name, count in (metrics.get("pathogen_frequency") or {}).items():
        lines.append(f"- **{name}** — marked rising on {count} day(s)")
    if not metrics.get("pathogen_frequency"):
        lines.append("- No rising-pathogen history in window.")

    lines += ["", "## Headline Leads Captured During the Week", "", "### Domestic", ""]
    for t in (metrics.get("headline_leads") or {}).get("domestic") or []:
        lines.append(f"- {t}")
    if not (metrics.get("headline_leads") or {}).get("domestic"):
        lines.append("- None stored.")
    lines += ["", "### International", ""]
    for t in (metrics.get("headline_leads") or {}).get("foreign") or []:
        lines.append(f"- {t}")
    if not (metrics.get("headline_leads") or {}).get("foreign"):
        lines.append("- None stored.")

    lines += ["", "## Discussion Questions", ""]
    qs = prose.get("discussion_questions") or []
    if isinstance(qs, str):
        qs = daily._normalize_watch_items(qs)
    for i, q in enumerate(qs[:7], 1):
        lines.append(f"{i}. {q}")
    if not qs:
        lines += [
            "1. Which theater showed the worst week-over-week movement, and is that still true today?",
            "2. Which pathogen trend is most operationally relevant for the group’s AO?",
            "3. What single watch item should the group re-check mid-week?",
        ]

    lines += ["", "## Watch Next Week", ""]
    watch = prose.get("watch_next_week") or []
    if isinstance(watch, str):
        watch = daily._normalize_watch_items(watch)
    for w in watch[:8]:
        lines.append(f"- {w}")
    if not watch:
        for name, _ in list((metrics.get("priority_frequency") or {}).items())[:4]:
            lines.append(f"- Continue priority watch: {name}")
        for name, _ in list((metrics.get("pathogen_frequency") or {}).items())[:2]:
            lines.append(f"- Track wastewater trend: {name}")

    lines += ["", "## Decision / Check Points", ""]
    dec = prose.get("decision_points") or []
    if isinstance(dec, str):
        dec = daily._normalize_watch_items(dec)
    for d in dec[:5]:
        lines.append(f"- {d}")
    if not dec:
        lines += [
            "- Confirm whether any priority theater requires an out-of-cycle update before next week.",
            "- Assign owner to re-check rising pathogen leaders mid-week.",
            "- Align on one shared common operating picture source (daily HTML brief).",
        ]

    if live and isinstance(live.get("threat_level"), dict):
        tl = live["threat_level"]
        lines += [
            "",
            "## Live Snapshot at Generation",
            "",
            f"- Platform threat: **{tl.get('level')}** ({tl.get('score')})",
        ]
        for dr in (tl.get("drivers") or [])[:5]:
            lines.append(f"- {dr}")

    lines += [
        "",
        "---",
        "",
        "## Methodology",
        "",
        "Built from the rolling daily history JSON written by the morning PAT Labs brief "
        f"(retention ~{daily.HISTORY_DAYS} days). Weekly window = last {WEEK_DAYS} calendar days "
        "present in that file. Open-source only; wastewater lags sampling. "
        "Not medical, legal, or operational orders — a structured meeting aid.",
        "",
        f"_History file: `{daily.HISTORY_JSON}`_",
        "",
    ]
    return "\n".join(lines)


def render_weekly_html(md: str, metrics: dict[str, Any]) -> str:
    """Email-safe table layout matching the daily executive style."""
    title_start = metrics.get("date_start") or "—"
    title_end = metrics.get("date_end") or "—"
    title = f"PAT Labs Weekly Intel — {title_start} to {title_end}"
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

    def bullets_html(text: str) -> str:
        items = daily._md_bullets(text)
        if not items:
            # numbered list
            for line in text.splitlines():
                m = re.match(r"^\d+\.\s+(.+)$", line.strip())
                if m:
                    items.append(m.group(1).strip())
        if not items and text.strip():
            items = [text.strip()]
        rows = "".join(
            f'<tr><td width="18" valign="top" style="padding:6px 0;font-size:12px;color:#94a3b8;">•</td>'
            f'<td style="padding:6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;'
            f'color:#1e293b;line-height:1.45;">{esc(re.sub(r"\*\*(.+?)\*\*", r"\1", it))}</td></tr>'
            for it in items
        )
        return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'

    # Metrics table rows
    mrows = ""
    for d in metrics.get("days") or []:
        pt = d.get("platform_threat") or {}
        st = d.get("strategic") or {}
        met = d.get("metrics") or {}
        mrows += (
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(d.get("date"))}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;font-weight:700;">{esc(f"{pt.get("score")}/{pt.get("level")}")}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(f"{st.get("overall_risk_score")}/{st.get("overall_risk_word")}")}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(met.get("pathogens_rising") if met.get("pathogens_rising") is not None else "—")}</td>'
            f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;">{esc(met.get("military_flights") if met.get("military_flights") is not None else "—")}</td>'
            "</tr>"
        )

    movement = ""
    for c in metrics.get("changes") or []:
        arrow = "↑" if c.get("direction") == "up" else ("↓" if c.get("direction") == "down" else "→")
        color = "#b91c1c" if c.get("direction") == "up" and "score" in str(c.get("metric")) else "#0f172a"
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
    PAT Labs weekly intel {esc(title_start)} to {esc(title_end)}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#e8eef4;">
    <tr><td align="center" style="padding:20px 12px;">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background:#ffffff;border:1px solid #d0d7de;">

        <tr><td style="background:#0b1f33;padding:20px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">
            PAT Labs · Weekly Intelligence Pack
          </div>
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;color:#ffffff;margin-top:6px;">
            Weekly Intel Meeting Brief
          </div>
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#8ba3b7;margin-top:6px;">
            {esc(title_start)} → {esc(title_end)} · {esc(metrics.get("days_available"))} daily snapshots · Generated {esc(gen)}
          </div>
        </td></tr>

        <tr><td style="padding:22px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:12px;">
            Situation Overview
          </div>
          {paras_html(section_body("Situation Overview"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:10px;">
            Week-at-a-Glance
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
            Score Movement
          </div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            {movement or '<tr><td style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">Insufficient multi-day data.</td></tr>'}
          </table>
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Theaters Most Often on Priority Watch
          </div>
          {bullets_html(section_body("Theaters Most Often on Priority Watch"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Biosecurity
          </div>
          {bullets_html(section_body("Biosecurity — Pathogens Most Often Rising"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Discussion Questions
          </div>
          {bullets_html(section_body("Discussion Questions"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Watch Next Week
          </div>
          {bullets_html(section_body("Watch Next Week"))}
        </td></tr>

        <tr><td style="padding:16px 24px 8px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
            Decision / Check Points
          </div>
          {bullets_html(section_body("Decision / Check Points"))}
        </td></tr>

        <tr><td style="padding:20px 24px 24px 24px;">
          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:14px;margin-bottom:8px;">
            Methodology
          </div>
          <p style="margin:0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#94a3b8;line-height:1.5;">
            Aggregated from daily PAT Labs snapshots (fixed history JSON). Open-source feeds; wastewater sampling lags.
            For meeting use — not medical, legal, or operational orders.
          </p>
          <p style="margin:12px 0 0 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#cbd5e1;letter-spacing:0.06em;text-transform:uppercase;">
            PAT Labs · Weekly Intelligence Pack
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
