#!/usr/bin/env python3
"""Shadowbroker 24-hour family brief — fixed filenames, Ollama narrative, email HTML.

Writes (overwrites, no timestamps):
  ~/Desktop/Daily_Inspiration/shadowbroker_24h_brief.md
  ~/Desktop/Daily_Inspiration/shadowbroker_24h_brief.html

Uses local Ollama (default model: olmo-3:32b-think) plus Shadowbroker live data
and the latest strategic delta brief.

Optional SMTP (HTML body) when DAILY_BRIEF_SMTP_* or DELTA_REPORT_SMTP_* are set.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

# ── Config ──────────────────────────────────────────────────────────────────

SB_BASE = os.environ.get("SHADOWBROKER_URL", "http://127.0.0.1:3050").rstrip("/")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("DAILY_BRIEF_OLLAMA_MODEL", "olmo-3:32b-think")
OUT_DIR = Path(
    os.environ.get(
        "DAILY_BRIEF_OUT_DIR",
        str(Path.home() / "Desktop" / "Daily_Inspiration"),
    )
).expanduser()
OUT_MD = OUT_DIR / "shadowbroker_24h_brief.md"
OUT_HTML = OUT_DIR / "shadowbroker_24h_brief.html"
# Fixed-name rolling history — overwritten in place, no dated copies.
# Default retention 14 days so weekly intel can use a full week; daily UI still shows 3 days.
HISTORY_JSON = Path(
    os.environ.get(
        "DAILY_BRIEF_HISTORY_JSON",
        str(OUT_DIR / "pat_labs_threat_history.json"),
    )
).expanduser()
# Backward-compatible alias if only the older 3d filename exists
HISTORY_JSON_LEGACY = OUT_DIR / "pat_labs_threat_history_3d.json"
HISTORY_DAYS = max(1, int(os.environ.get("DAILY_BRIEF_HISTORY_DAYS", "14") or "14"))
PROGRESSION_DISPLAY_DAYS = max(1, int(os.environ.get("DAILY_BRIEF_PROGRESSION_DAYS", "3") or "3"))
DELTA_MD_CANDIDATES = [
    Path.home() / "Desktop" / "Daily_Inspiration" / "Shadowbroker_Strategic_Delta.md",
    Path("/home/bob/Desktop/Daily_Inspiration/Shadowbroker_Strategic_Delta.md"),
    Path(__file__).resolve().parents[1] / "backend" / "data" / "delta_reports" / "latest.md",
]

US_HINTS = re.compile(
    r"\b(U\.?S\.?|United States|America|Washington|Pentagon|White House|"
    r"California|Texas|New York|Florida|Baltimore|Congress|FBI|DHS|"
    r"CDC|FEMA|border|border patrol)\b",
    re.I,
)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _http_json(url: str, *, timeout: float = 90, method: str = "GET", body: dict | None = None) -> Any:
    data = None
    headers = {"User-Agent": "Shadowbroker-Daily24hBrief/1.0", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _clip(s: str, n: int = 220) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


# ── Data collection ─────────────────────────────────────────────────────────


def load_delta_markdown() -> str:
    for path in DELTA_MD_CANDIDATES:
        try:
            if path.is_file() and path.stat().st_size > 200:
                text = path.read_text(encoding="utf-8", errors="replace")
                # Keep a usable slice for the LLM + report
                lines = text.splitlines()
                return "\n".join(lines[:180])
        except OSError:
            continue
    return ""


def fetch_slow_intel() -> dict[str, Any]:
    url = f"{SB_BASE}/api/live-data/slow"
    try:
        return _http_json(url, timeout=120)
    except Exception as exc:
        print(f"[warn] live-data/slow failed: {exc}", file=sys.stderr)
        return {}


def _news_item(n: dict[str, Any]) -> dict[str, str]:
    title = str(n.get("title") or n.get("headline") or "").strip()
    source = str(n.get("source") or n.get("publisher") or n.get("country") or "").strip()
    link = str(n.get("link") or n.get("url") or n.get("source_url") or "").strip()
    published = str(n.get("published") or n.get("date") or n.get("timestamp") or "").strip()
    summary = str(n.get("summary") or n.get("description") or n.get("snippet") or "").strip()
    return {
        "title": _clip(title, 180),
        "source": source,
        "link": link,
        "published": published,
        "summary": _clip(summary, 280),
    }


def split_news(news: list[Any], *, limit: int = 18) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    domestic: list[dict[str, str]] = []
    foreign: list[dict[str, str]] = []
    for raw in news:
        if not isinstance(raw, dict):
            continue
        item = _news_item(raw)
        if not item["title"]:
            continue
        blob = f"{item['title']} {item['summary']} {item['source']}"
        if US_HINTS.search(blob):
            domestic.append(item)
        else:
            foreign.append(item)
    return domestic[:limit], foreign[:limit]


def extract_gdelt_hotspots(gdelt: list[Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feat in gdelt:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else feat
        if not isinstance(props, dict):
            continue
        headlines = props.get("_headlines_list") or []
        headline = ""
        if isinstance(headlines, list) and headlines:
            headline = str(headlines[0])
        name = str(props.get("name") or "").strip()
        goldstein = props.get("goldstein")
        try:
            g = float(goldstein) if goldstein is not None else 0.0
        except (TypeError, ValueError):
            g = 0.0
        mentions = int(props.get("num_mentions") or props.get("count") or 0)
        # Prefer conflict / negative tone
        if g > -2 and mentions < 3 and not headline:
            continue
        rows.append(
            {
                "place": _clip(name, 80),
                "headline": _clip(headline, 160),
                "goldstein": g,
                "mentions": mentions,
                "actors": props.get("actors") or [],
                "date": str(props.get("event_date") or ""),
            }
        )
    rows.sort(key=lambda r: (r["goldstein"], -r["mentions"]))
    return rows[:limit]


def extract_telegram(items: list[Any], *, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("text") or raw.get("description") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": _clip(title, 200),
                "channel": str(raw.get("channel") or raw.get("source") or "").strip(),
                "risk": str(raw.get("risk_score") or raw.get("risk") or "").strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


def wastewater_section(surv: dict[str, Any] | None) -> dict[str, Any]:
    surv = surv if isinstance(surv, dict) else {}
    pathogens = surv.get("pathogens") if isinstance(surv.get("pathogens"), list) else []
    rising = surv.get("rising_pathogens") if isinstance(surv.get("rising_pathogens"), list) else []
    if not rising:
        rising = [p for p in pathogens if isinstance(p, dict) and str(p.get("trend") or "").lower() == "rising"]
    return {
        "updated_at": surv.get("updated_at"),
        "baseline_date": surv.get("baseline_date"),
        "plants_monitored": surv.get("plants_monitored"),
        "plants_active": surv.get("plants_active"),
        "pathogens_rising": surv.get("pathogens_rising"),
        "latest_collection_date": surv.get("latest_collection_date"),
        "median_sample_age_days": surv.get("median_sample_age_days"),
        "rising": [
            {
                "name": p.get("name"),
                "states_rising": p.get("states_rising"),
                "sites_rising": p.get("sites_rising"),
                "states_alert": p.get("states_alert"),
                "sites_alert": p.get("sites_alert"),
                "rising_rate_display": p.get("rising_rate_display"),
                "trend": p.get("trend"),
            }
            for p in rising
            if isinstance(p, dict)
        ],
        "stable_or_falling": [
            {
                "name": p.get("name"),
                "trend": p.get("trend"),
                "states_rising": p.get("states_rising"),
            }
            for p in pathogens
            if isinstance(p, dict) and str(p.get("trend") or "").lower() != "rising"
        ][:8],
    }


def collect_context() -> dict[str, Any]:
    slow = fetch_slow_intel()
    news = slow.get("news") if isinstance(slow.get("news"), list) else []
    domestic, foreign = split_news(news)
    gdelt = slow.get("gdelt") if isinstance(slow.get("gdelt"), list) else []
    telegram = slow.get("telegram_osint") if isinstance(slow.get("telegram_osint"), list) else []
    threat = slow.get("threat_level") if isinstance(slow.get("threat_level"), dict) else {}
    ww = wastewater_section(slow.get("wastewater_surveillance") if isinstance(slow.get("wastewater_surveillance"), dict) else {})
    delta_md = load_delta_markdown()
    return {
        "generated_at": _now_local().isoformat(timespec="seconds"),
        "window": "past ~24 hours (feeds as available; wastewater sampling lags)",
        "threat_level": threat,
        "domestic_news": domestic,
        "foreign_news": foreign,
        "gdelt_hotspots": extract_gdelt_hotspots(gdelt),
        "telegram_osint": extract_telegram(telegram),
        "wastewater": ww,
        "delta_excerpt": delta_md,
        "source_counts": {
            "news": len(news),
            "gdelt": len(gdelt),
            "telegram": len(telegram),
            "earthquakes": len(slow.get("earthquakes") or []) if isinstance(slow.get("earthquakes"), list) else 0,
        },
    }


# ── 3-day rolling history ───────────────────────────────────────────────────


def _parse_delta_metrics(delta_md: str) -> dict[str, Any]:
    """Pull coarse strategic metrics from delta markdown (no invention)."""
    out: dict[str, Any] = {
        "overall_risk_word": None,
        "overall_risk_score": None,
        "trend": None,
        "critical_flashpoints": None,
        "priorities": [],
        "region_shifts": [],
        "domestic_watch": None,
    }
    if not delta_md:
        return out
    for line in delta_md.splitlines():
        s = line.strip()
        m = re.match(r"(?i)overall risk:\s*(\w+)", s)
        if m:
            out["overall_risk_word"] = m.group(1).upper()
        m = re.search(r"(?i)(\d+)\s*/\s*100", s)
        if m and out.get("overall_risk_score") is None and "risk" in s.lower():
            try:
                out["overall_risk_score"] = int(m.group(1))
            except ValueError:
                pass
        # Global Strategic Risk gauge often sits on its own line: "65 / 100"
        m = re.match(r"^(\d+)\s*/\s*100\s*$", s)
        if m:
            try:
                out["overall_risk_score"] = int(m.group(1))
            except ValueError:
                pass
        m = re.match(r"(?i)trend:\s*(.+)$", s)
        if m:
            out["trend"] = m.group(1).strip()
        m = re.match(r"(?i)critical flashpoints:\s*(\d+)", s)
        if m:
            try:
                out["critical_flashpoints"] = int(m.group(1))
            except ValueError:
                pass
        m = re.search(r"(?i)domestic watch:\s*([^.;]+)", s)
        if m:
            out["domestic_watch"] = m.group(1).strip()
        m = re.search(
            r"(?i)priority\s+(\d+)\s*[·•\-]\s*(?:⛔|⚠|⚠️)?\s*(.+?)(?:\s*\[([^\]]*)\])?\s*$",
            s,
        )
        if m:
            region = re.sub(r"^[⛔⚠⚠️▲▼↑↓·\-\s]+", "", m.group(2).strip())
            out["priorities"].append(
                {
                    "rank": int(m.group(1)),
                    "region": region,
                    "delta": (m.group(3) or "").strip(),
                }
            )
        m = re.match(r"(?i)[•\-]\s*Region\s+(\S+)\s+risk\s+(\d+)%\s*→\s*(\d+)%", s)
        if m:
            out["region_shifts"].append(
                {
                    "region": m.group(1),
                    "from": int(m.group(2)),
                    "to": int(m.group(3)),
                    "delta": int(m.group(3)) - int(m.group(2)),
                }
            )
    out["priorities"] = out["priorities"][:6]
    out["region_shifts"] = out["region_shifts"][:10]
    return out


def _parse_mil_flights(threat: dict[str, Any], delta_md: str) -> int | None:
    for d in threat.get("drivers") or []:
        m = re.search(r"(?i)military flight[s]?[^0-9]*(\d+)", str(d))
        if m:
            return int(m.group(1))
    m = re.search(r"(?i)military flight[s]?[^0-9]*(\d+)", delta_md or "")
    if m:
        return int(m.group(1))
    return None


def build_day_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compact one-day record for the rolling history JSON."""
    when = _now_local()
    day = when.date().isoformat()
    threat = ctx.get("threat_level") if isinstance(ctx.get("threat_level"), dict) else {}
    ww = ctx.get("wastewater") if isinstance(ctx.get("wastewater"), dict) else {}
    sc = ctx.get("source_counts") or {}
    delta_bits = _parse_delta_metrics(ctx.get("delta_excerpt") or "")

    try:
        platform_score = int(float(threat.get("score"))) if threat.get("score") is not None else None
    except (TypeError, ValueError):
        platform_score = None

    rising = []
    for p in ww.get("rising") or []:
        if not isinstance(p, dict):
            continue
        rising.append(
            {
                "name": p.get("name"),
                "states_rising": p.get("states_rising"),
                "sites_rising": p.get("sites_rising"),
                "sites_alert": p.get("sites_alert"),
                "rising_rate_display": p.get("rising_rate_display"),
            }
        )

    domestic_titles = [
        str(n.get("title") or "").strip()
        for n in (ctx.get("domestic_news") or [])[:5]
        if n.get("title")
    ]
    foreign_titles = [
        str(n.get("title") or "").strip()
        for n in (ctx.get("foreign_news") or [])[:5]
        if n.get("title")
    ]

    return {
        "date": day,
        "captured_at": when.isoformat(timespec="seconds"),
        "platform_threat": {
            "level": threat.get("level"),
            "score": platform_score,
            "drivers": list(threat.get("drivers") or [])[:6],
        },
        "strategic": {
            "overall_risk_word": delta_bits.get("overall_risk_word"),
            "overall_risk_score": delta_bits.get("overall_risk_score"),
            "trend": delta_bits.get("trend"),
            "critical_flashpoints": delta_bits.get("critical_flashpoints"),
            "priorities": delta_bits.get("priorities") or [],
            "region_shifts": delta_bits.get("region_shifts") or [],
            "domestic_watch": delta_bits.get("domestic_watch"),
        },
        "metrics": {
            "military_flights": _parse_mil_flights(threat, ctx.get("delta_excerpt") or ""),
            "news_count": sc.get("news"),
            "gdelt_count": sc.get("gdelt"),
            "telegram_count": sc.get("telegram"),
            "earthquakes": sc.get("earthquakes"),
            "pathogens_rising": ww.get("pathogens_rising"),
            "plants_active": ww.get("plants_active"),
            "plants_monitored": ww.get("plants_monitored"),
            "latest_collection_date": ww.get("latest_collection_date"),
            "median_sample_age_days": ww.get("median_sample_age_days"),
        },
        "pathogens_rising": rising[:12],
        "headline_leads": {
            "domestic": domestic_titles,
            "foreign": foreign_titles,
        },
    }


def load_history() -> dict[str, Any]:
    candidates = [HISTORY_JSON]
    if HISTORY_JSON_LEGACY not in candidates:
        candidates.append(HISTORY_JSON_LEGACY)
    for path in candidates:
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("days"), list):
                    return raw
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] history load failed ({path}): {exc}", file=sys.stderr)
    return {
        "schema": "pat_labs_threat_history/v1",
        "retention_days": HISTORY_DAYS,
        "updated_at": None,
        "days": [],
    }


def save_history(doc: dict[str, Any]) -> Path:
    HISTORY_JSON.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    doc["schema"] = "pat_labs_threat_history/v1"
    doc["retention_days"] = HISTORY_DAYS
    doc["updated_at"] = _now_local().isoformat(timespec="seconds")
    # Atomic-ish replace
    tmp = HISTORY_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(HISTORY_JSON)
    try:
        HISTORY_JSON.chmod(0o644)
    except OSError:
        pass
    # Keep legacy filename in sync for older tools/paths
    try:
        if HISTORY_JSON_LEGACY != HISTORY_JSON:
            HISTORY_JSON_LEGACY.write_text(
                HISTORY_JSON.read_text(encoding="utf-8"), encoding="utf-8"
            )
            HISTORY_JSON_LEGACY.chmod(0o644)
    except OSError:
        pass
    return HISTORY_JSON


def upsert_history(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Insert/replace today's snapshot; keep only last HISTORY_DAYS calendar days."""
    doc = load_history()
    days = [d for d in (doc.get("days") or []) if isinstance(d, dict) and d.get("date")]
    today = snapshot.get("date")
    days = [d for d in days if d.get("date") != today]
    days.append(snapshot)
    days.sort(key=lambda d: str(d.get("date") or ""))
    # Keep last N unique dates
    if len(days) > HISTORY_DAYS:
        days = days[-HISTORY_DAYS:]
    doc["days"] = days
    save_history(doc)
    return doc


def compute_progression(doc: dict[str, Any]) -> dict[str, Any]:
    """Day-over-day deltas for LLM + HTML (facts only)."""
    days = [d for d in (doc.get("days") or []) if isinstance(d, dict)]
    days = sorted(days, key=lambda d: str(d.get("date") or ""))
    if not days:
        return {"days_available": 0, "series": [], "changes": [], "summary_lines": []}

    # Daily brief progression panel: last N days only (default 3)
    days = days[-PROGRESSION_DISPLAY_DAYS:]

    series = []
    for d in days:
        pt = d.get("platform_threat") or {}
        st = d.get("strategic") or {}
        met = d.get("metrics") or {}
        series.append(
            {
                "date": d.get("date"),
                "platform_score": pt.get("score"),
                "platform_level": pt.get("level"),
                "strategic_score": st.get("overall_risk_score"),
                "strategic_level": st.get("overall_risk_word"),
                "trend": st.get("trend"),
                "critical_flashpoints": st.get("critical_flashpoints"),
                "pathogens_rising": met.get("pathogens_rising"),
                "military_flights": met.get("military_flights"),
                "news_count": met.get("news_count"),
                "top_priorities": [
                    p.get("region") for p in (st.get("priorities") or [])[:3] if isinstance(p, dict)
                ],
                "top_pathogens": [
                    p.get("name") for p in (d.get("pathogens_rising") or [])[:4] if isinstance(p, dict)
                ],
            }
        )

    changes: list[dict[str, Any]] = []
    summary_lines: list[str] = []

    def _num(v: Any) -> float | None:
        try:
            if v is None:
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    if len(series) >= 2:
        prev, cur = series[-2], series[-1]
        for key, label in (
            ("platform_score", "Platform threat score"),
            ("strategic_score", "Strategic risk score"),
            ("pathogens_rising", "Pathogens rising"),
            ("military_flights", "Military flights tracked"),
            ("critical_flashpoints", "Critical flashpoints"),
            ("news_count", "News items"),
        ):
            a, b = _num(prev.get(key)), _num(cur.get(key))
            if a is None or b is None:
                continue
            delta = b - a
            direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            changes.append(
                {
                    "metric": key,
                    "label": label,
                    "from_date": prev.get("date"),
                    "to_date": cur.get("date"),
                    "from": a,
                    "to": b,
                    "delta": delta,
                    "direction": direction,
                }
            )
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            summary_lines.append(
                f"{label}: {a:g} → {b:g} ({arrow}{abs(delta):g}) [{prev.get('date')} → {cur.get('date')}]"
            )

        # Priority set changes
        prev_pri = set(prev.get("top_priorities") or [])
        cur_pri = set(cur.get("top_priorities") or [])
        entered = sorted(cur_pri - prev_pri)
        exited = sorted(prev_pri - cur_pri)
        if entered:
            summary_lines.append("New priority theaters: " + ", ".join(entered))
        if exited:
            summary_lines.append("Dropped from top priorities: " + ", ".join(exited))

        prev_path = set(prev.get("top_pathogens") or [])
        cur_path = set(cur.get("top_pathogens") or [])
        new_path = sorted(cur_path - prev_path)
        gone_path = sorted(prev_path - cur_path)
        if new_path:
            summary_lines.append("Newly prominent rising pathogens: " + ", ".join(new_path))
        if gone_path:
            summary_lines.append("No longer in top rising list: " + ", ".join(gone_path))
    else:
        summary_lines.append(
            f"Only {len(series)} day(s) of history so far — progression strengthens after 2–3 daily runs."
        )

    # 3-day platform score trail
    trail = [
        f"{s.get('date')}: platform {s.get('platform_score')}/{s.get('platform_level')}"
        + (
            f", strategic {s.get('strategic_score')}/{s.get('strategic_level')}"
            if s.get("strategic_score") is not None or s.get("strategic_level")
            else ""
        )
        for s in series
    ]
    if trail:
        summary_lines.insert(0, "Score trail: " + " · ".join(trail))

    return {
        "days_available": len(series),
        "retention_days": HISTORY_DAYS,
        "series": series,
        "changes": changes,
        "summary_lines": summary_lines,
        "history_path": str(HISTORY_JSON),
    }


# ── Ollama ──────────────────────────────────────────────────────────────────


def build_facts_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compact structured facts for the model — no raw multi-MB dump."""
    return {
        "generated_at": ctx["generated_at"],
        "threat_level": ctx["threat_level"],
        "wastewater_rising": ctx["wastewater"].get("rising"),
        "wastewater_meta": {
            k: ctx["wastewater"].get(k)
            for k in (
                "plants_active",
                "pathogens_rising",
                "latest_collection_date",
                "baseline_date",
                "median_sample_age_days",
            )
        },
        "domestic_news": ctx["domestic_news"][:12],
        "foreign_news": ctx["foreign_news"][:12],
        "gdelt_hotspots": ctx["gdelt_hotspots"][:10],
        "telegram_osint": ctx["telegram_osint"][:6],
        "strategic_delta_excerpt": (ctx.get("delta_excerpt") or "")[:4500],
    }


def _ollama_chat(system: str, user: str, *, num_predict: int = 900) -> str:
    options = {"temperature": 0.2, "num_predict": num_predict, "top_p": 0.9}
    try:
        data = _http_json(
            f"{OLLAMA_URL}/api/chat",
            timeout=600,
            method="POST",
            body={
                "model": OLLAMA_MODEL,
                "stream": False,
                "options": options,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        return str((msg or {}).get("content") or data.get("response") or "").strip()
    except Exception as exc:
        print(f"[warn] Ollama chat failed: {exc}", file=sys.stderr)
        return ""


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
    return None


def _briefing_facts_for_llm(ctx: dict[str, Any]) -> dict[str, Any]:
    """Richer fact pack for Ollama (still capped — not the multi-MB live dump)."""
    facts = build_facts_payload(ctx)
    rising = []
    for p in facts.get("wastewater_rising") or []:
        if not isinstance(p, dict):
            continue
        rising.append(
            {
                "name": p.get("name"),
                "states_rising": p.get("states_rising"),
                "sites_rising": p.get("sites_rising"),
                "sites_alert": p.get("sites_alert"),
                "rising_rate_display": p.get("rising_rate_display"),
            }
        )
    domestic = []
    for n in facts.get("domestic_news") or []:
        domestic.append(
            {
                "title": n.get("title"),
                "source": n.get("source"),
                "summary": (n.get("summary") or "")[:180],
            }
        )
    foreign = []
    for n in facts.get("foreign_news") or []:
        foreign.append(
            {
                "title": n.get("title"),
                "source": n.get("source"),
                "summary": (n.get("summary") or "")[:180],
            }
        )
    gdelt = []
    for g in facts.get("gdelt_hotspots") or []:
        gdelt.append(
            {
                "place": g.get("place"),
                "headline": g.get("headline"),
                "goldstein": g.get("goldstein"),
                "mentions": g.get("mentions"),
            }
        )
    return {
        "threat_level": facts.get("threat_level"),
        "wastewater_meta": facts.get("wastewater_meta"),
        "pathogens_rising": rising,
        "domestic_news": domestic[:12],
        "foreign_news": foreign[:12],
        "gdelt_hotspots": gdelt[:10],
        "strategic_delta_excerpt": "\n".join(
            (facts.get("strategic_delta_excerpt") or "").splitlines()[:120]
        ),
        "three_day_progression": (ctx.get("progression") or {}).get("summary_lines")
        or [],
        "three_day_series": (ctx.get("progression") or {}).get("series") or [],
    }


def ollama_prose_bits(ctx: dict[str, Any]) -> dict[str, str]:
    """Ollama writes the narrative prose; code still owns section structure/tables.

    Executive summary is a dedicated richer call so it is not starved by the
    short JSON bundle used for watch-list / threat blurb.
    """
    pack = _briefing_facts_for_llm(ctx)
    pack_json = json.dumps(pack, ensure_ascii=False, indent=2)

    system = (
        "You are the lead analyst for PAT Labs Threat Assessment. "
        "Write finished prose only. Use ONLY provided facts. "
        "Never invent places, numbers, or events. No medical advice, no panic. "
        "Wastewater is environmental surveillance, not diagnosis. "
        "FORBIDDEN: markdown headings (# ## ###), bullet lists, numbered outlines, "
        "section labels like 'Strategic Overview' or 'Recommendations', "
        "and openers like 'Based on the provided data'."
    )

    # ── 1) Full executive summary (multi-paragraph plain text) ─────────────
    exec_user = f"""Write the Executive Summary as 3 continuous paragraphs of plain English (220–400 words total).

Must include when facts allow: overall risk/score and trend; top flashpoints by name; 3-day score movement if three_day_series exists; notable rising pathogens with rates; 1–2 concrete headlines with outlets; what matters next.

Output rules (strict):
- ONLY paragraph text separated by blank lines
- NO markdown of any kind (no #, ###, -, *, 1., bold **)
- NO section titles
- NO incomplete lists or trailing colons with empty content
- Start with the situation, not meta commentary

Facts:
{pack_json}
"""
    executive = _ollama_chat(system, exec_user, num_predict=2200)
    executive = _clean_exec_prose(executive)
    if not _exec_prose_ok(executive):
        print("[warn] executive summary failed quality check — retrying once", file=sys.stderr)
        retry = (
            "Rewrite as THREE plain paragraphs only. Zero markdown. Zero headings. "
            "Zero bullets. Include scores, flashpoints, pathogens, and trend from the facts.\n\n"
            f"Facts:\n{pack_json}"
        )
        executive = _clean_exec_prose(_ollama_chat(system, retry, num_predict=1800))
    if not _exec_prose_ok(executive):
        print("[warn] executive summary still poor — using structured fallback", file=sys.stderr)
        executive = ""

    # ── 2) Supporting fields as JSON ───────────────────────────────────────
    support_user = f"""Return JSON only (no markdown fences) with exactly these keys:
- "what_to_watch": array of 5–7 short concrete watch items (strings), each grounded in the facts (flashpoints, pathogens, named headlines). No vague filler.
- "threat_blurb": 3–5 sentences translating strategic risk for non-experts; mention overall risk score/level and the top flashpoints if present.
- "progression_blurb": 2–4 sentences on how the last 2–3 days compare (use three_day_progression numbers only; if only one day of history, say baseline day).

Facts:
{pack_json}
"""
    support_raw = _ollama_chat(system, support_user, num_predict=1400)
    support = _parse_json_object(support_raw) or {}

    what = support.get("what_to_watch")
    if isinstance(what, list):
        what_to_watch = json.dumps(what, ensure_ascii=False)
    else:
        what_to_watch = str(what or "").strip()

    threat_blurb = str(support.get("threat_blurb") or "").strip()
    progression_blurb = str(support.get("progression_blurb") or "").strip()

    if not executive:
        print("[warn] Ollama executive summary empty", file=sys.stderr)
    else:
        print(f"[info] executive summary ~{len(executive.split())} words")

    return {
        "executive_summary": executive,
        "what_to_watch": what_to_watch,
        "threat_blurb": threat_blurb,
        "progression_blurb": progression_blurb,
    }


def _strip_think_traces(text: str) -> str:
    """Remove chain-of-thought blocks from think-style models (e.g. olmo-3:32b-think)."""
    t = text or ""
    # XML-style / common Ollama think wrappers
    for pat in (
        r"(?is)<think\b[^>]*>.*?</think>",
        r"(?is)<thinking\b[^>]*>.*?</thinking>",
        r"(?is)<reasoning\b[^>]*>.*?</reasoning>",
        r"(?is)<\|thinking\|>.*?<\|/thinking\|>",
        r"(?is)<\|begin_of_thought\|>.*?<\|end_of_thought\|>",
    ):
        t = re.sub(pat, "", t)
    # If the model dumps a long "Thinking:" preamble then a Final answer:
    m = re.search(
        r"(?is)(?:^|\n)\s*(?:final\s+answer|answer|executive\s+summary|situation\s+overview)\s*[:\-]\s*",
        t,
    )
    if m and m.start() > 80:
        t = t[m.end() :]
    return t.strip()


def _clean_exec_prose(text: str) -> str:
    """Strip chatty wrappers and markdown outlines; keep multi-paragraph prose."""
    t = _strip_think_traces((text or "").strip())
    if not t:
        return ""
    # Drop accidental JSON wrapper
    if t.startswith("{") and "executive" in t[:80].lower():
        obj = _parse_json_object(t)
        if obj and obj.get("executive_summary"):
            t = str(obj["executive_summary"]).strip()
            t = _strip_think_traces(t)

    # If model returned an outline, flatten heading+bullets into sentences
    if re.search(r"(?m)^#{1,6}\s+", t) or re.search(r"(?m)^(\d+\.|[-*])\s+\S", t):
        t = _outline_to_prose(t)

    lines = t.splitlines()
    while lines and re.match(
        r"(?i)^(here('s| is)|sure[,.]|below is|executive summary\s*:|"
        r"based on the provided data|comprehensive analysis)\b",
        lines[0].strip(),
    ):
        lines.pop(0)
    # Drop leftover pure heading / empty-label lines
    cleaned: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append("")
            continue
        if re.match(r"^#{1,6}\s+", s):
            # heading-only → skip (content should already be flattened)
            continue
        if re.match(r"(?i)^(strategic overview|key flashpoints|recent changes|"
                    r"pathogen situation|military activity|news coverage|"
                    r"recommendations)\s*:?\s*$", s):
            continue
        if re.match(r"(?i)^\d+\.\s+\w[\w\s/&-]*:\s*$", s):
            # "1. Score Progression:" with no body
            continue
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*]\s+", "", s)
        s = re.sub(r"^\d+\.\s+", "", s)
        cleaned.append(s)

    # Collapse to paragraphs on blank lines
    paras: list[str] = []
    buf: list[str] = []
    for s in cleaned:
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
    if buf:
        paras.append(" ".join(buf))

    t = "\n\n".join(p.strip() for p in paras if p.strip())
    # Remove meta openers mid-text
    t = re.sub(
        r"(?i)^based on the provided data,?\s*here'?s a comprehensive analysis[^:]*:\s*",
        "",
        t,
    ).strip()
    return t


def _outline_to_prose(text: str) -> str:
    """Turn markdown outline (headings + bullets) into paragraph blocks."""
    chunks: list[str] = []
    current_label = ""
    bullets: list[str] = []

    def flush() -> None:
        nonlocal current_label, bullets
        if not bullets and not current_label:
            return
        body = "; ".join(b.rstrip(".") for b in bullets if b.strip())
        if current_label and body:
            chunks.append(f"{current_label}: {body}.")
        elif body:
            chunks.append(body + ("" if body.endswith(".") else "."))
        elif current_label:
            # label alone — drop empty sections
            pass
        current_label = ""
        bullets = []

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            flush()
            continue
        hm = re.match(r"^#{1,6}\s+(.+)$", s)
        if hm:
            flush()
            current_label = re.sub(r"[:\s]+$", "", hm.group(1).strip())
            continue
        bm = re.match(r"^[-*]\s+(.+)$", s)
        if bm:
            bullets.append(re.sub(r"\*\*(.+?)\*\*", r"\1", bm.group(1).strip()))
            continue
        nm = re.match(r"^\d+\.\s+(.+)$", s)
        if nm:
            item = re.sub(r"\*\*(.+?)\*\*", r"\1", nm.group(1).strip())
            # "Score Progression:" alone → become label, not bullet
            if item.endswith(":") and len(item) < 60:
                flush()
                current_label = item.rstrip(":").strip()
            else:
                bullets.append(item)
            continue
        # plain sentence line
        flush()
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        if not re.match(
            r"(?i)^(based on the provided data|here'?s a comprehensive)",
            s,
        ):
            chunks.append(s if s.endswith((".", "!", "?")) else s + ".")

    flush()
    # Group into ~3 paragraphs
    if not chunks:
        return ""
    if len(chunks) <= 3:
        return "\n\n".join(chunks)
    n = len(chunks)
    a, b = max(1, n // 3), max(2, (2 * n) // 3)
    return "\n\n".join(
        [
            " ".join(chunks[:a]),
            " ".join(chunks[a:b]),
            " ".join(chunks[b:]),
        ]
    )


def _exec_prose_ok(text: str) -> bool:
    """Reject empty outlines / markdown shells from the model."""
    t = (text or "").strip()
    if len(t) < 120:
        return False
    words = len(t.split())
    if words < 40:
        return False
    heading_lines = len(re.findall(r"(?m)^#{1,6}\s+\S", t))
    if heading_lines >= 2:
        return False
    if t.count("###") >= 2:
        return False
    # Many empty section labels
    empty_labels = len(
        re.findall(
            r"(?im)^(strategic overview|key flashpoints|pathogen situation|"
            r"military activity|news coverage|recommendations)\s*:?\s*$",
            t,
        )
    )
    if empty_labels >= 2:
        return False
    if re.search(r"(?i)based on the provided data", t) and words < 80:
        return False
    # Truncated trailing header
    if re.search(r"(?i)recommendations for\s*$", t):
        return False
    return True


def _fallback_executive_summary(ctx: dict[str, Any]) -> str:
    """Denser non-LLM fallback if Ollama is down."""
    tl = ctx.get("threat_level") or {}
    level = tl.get("level") or "n/a"
    score = tl.get("score")
    drivers = tl.get("drivers") or []
    ww = ctx.get("wastewater") or {}
    rising = ww.get("rising") or []
    dom = ctx.get("domestic_news") or []
    foreign = ctx.get("foreign_news") or []
    delta_bits = _parse_delta_highlights(ctx.get("delta_excerpt") or "")

    p1 = (
        f"Over the past roughly 24 hours, open-source feeds put the platform posture at "
        f"**{level}**"
        + (f" ({score}/100)" if score is not None else "")
        + "."
    )
    if drivers:
        p1 += " Drivers include " + "; ".join(str(d) for d in drivers[:4]) + "."
    if delta_bits:
        p1 += " Strategic notes: " + " ".join(delta_bits[:4])

    path_bits = []
    for p in rising[:6]:
        path_bits.append(
            f"{p.get('name')} (~{p.get('sites_rising')} sites / {p.get('states_rising')} states, "
            f"{p.get('rising_rate_display') or 'n/a'})"
        )
    p2 = (
        f"Wastewater surveillance shows {ww.get('pathogens_rising') or len(rising)} pathogen(s) rising "
        f"across {ww.get('plants_active')} active plants "
        f"(latest collection {ww.get('latest_collection_date')}, "
        f"median sample age ~{ww.get('median_sample_age_days')} days)."
    )
    if path_bits:
        p2 += " Notable rising signals: " + "; ".join(path_bits) + "."

    headlines = []
    for n in (dom[:3] + foreign[:3]):
        if n.get("title"):
            src = f" ({n.get('source')})" if n.get("source") else ""
            headlines.append(f"{n.get('title')}{src}")
    p3 = "Headlines drawing attention include: " + "; ".join(headlines) + "." if headlines else (
        "Headline coverage in the current slice is thin."
    )
    return f"{p1}\n\n{p2}\n\n{p3}"


def _parse_delta_highlights(delta_md: str) -> list[str]:
    bullets: list[str] = []
    if not delta_md:
        return bullets
    for line in delta_md.splitlines():
        s = line.strip()
        if s.startswith("Overall Risk:") or s.startswith("Trend:") or s.startswith("Critical Flashpoints:"):
            bullets.append(s)
        if "Largest deteriorations" in s or "Improvements:" in s or "Domestic watch:" in s:
            bullets.append(s)
        if s.startswith("• ") or s.startswith("- "):
            if any(k in s.lower() for k in ("risk", "flashpoint", "strait", "taiwan", "ukraine", "hormuz", "protest", "china", "korea", "baltic")):
                bullets.append(s.lstrip("•- ").strip())
        if s.startswith("Priority ") and "·" in s:
            bullets.append(s)
        if len(bullets) >= 14:
            break
    return bullets[:14]


def assemble_narrative(ctx: dict[str, Any], prose: dict[str, str] | None = None) -> str:
    """Always-structured MD; Ollama fills prose fields when available."""
    prose = prose or {}
    tl = ctx.get("threat_level") or {}
    level = tl.get("level") or "n/a"
    score = tl.get("score")
    drivers = tl.get("drivers") or []

    exec_sum = _clean_exec_prose((prose.get("executive_summary") or "").strip())
    if not _exec_prose_ok(exec_sum):
        exec_sum = _fallback_executive_summary(ctx)

    threat_blurb = (prose.get("threat_blurb") or "").strip()
    # Multi-paragraph exec summary: blank line between paragraphs
    exec_block = "\n\n".join(
        p.strip() for p in re.split(r"\n\s*\n", exec_sum) if p.strip()
    )
    lines: list[str] = [
        "## Executive Summary",
        "",
        exec_block,
        "",
        "## Threat Matrix",
        "",
    ]
    if threat_blurb:
        lines += [threat_blurb, ""]
    lines.append(f"- Platform threat level: **{level}**" + (f" ({score}/100)" if score is not None else ""))
    for d in drivers[:6]:
        lines.append(f"- {d}")
    for b in _parse_delta_highlights(ctx.get("delta_excerpt") or ""):
        if b not in lines:
            lines.append(f"- {b}")

    lines += ["", "## Wastewater & Pathogens", ""]
    ww = ctx.get("wastewater") or {}
    rising = ww.get("rising") or []
    if not rising:
        lines.append("- No rising pathogen signals in the latest national surveillance rollup.")
    else:
        lines.append(
            f"US wastewater plants reporting (active): **{ww.get('plants_active')}** of "
            f"{ww.get('plants_monitored')}. Pathogens currently rising: **{ww.get('pathogens_rising')}**. "
            f"Latest collection date in feed: **{ww.get('latest_collection_date')}** "
            f"(median sample age ~{ww.get('median_sample_age_days')} days — this lag is normal)."
        )
        lines.append("")
        for p in rising:
            lines.append(
                f"- **{p.get('name')}**: rising at ~{p.get('sites_rising')} sites across "
                f"{p.get('states_rising')} states"
                f" (alert sites: {p.get('sites_alert')}; week-over-week rising rate "
                f"{p.get('rising_rate_display') or 'n/a'})."
            )
        lines.append("")
        lines.append(
            "_Wastewater reflects community shedding trends, not individual risk. "
            "It is not a substitute for clinical testing or public-health guidance._"
        )

    lines += ["", "## Domestic Updates", ""]
    for n in (ctx.get("domestic_news") or [])[:8]:
        src = f" ({n.get('source')})" if n.get("source") else ""
        lines.append(f"- {n.get('title')}{src}")
    if not ctx.get("domestic_news"):
        lines.append("- No US-tagged headlines in the current news slice.")

    lines += ["", "## International Updates", ""]
    for n in (ctx.get("foreign_news") or [])[:10]:
        src = f" ({n.get('source')})" if n.get("source") else ""
        lines.append(f"- {n.get('title')}{src}")
    for g in (ctx.get("gdelt_hotspots") or [])[:5]:
        if g.get("headline"):
            lines.append(f"- {g.get('headline')} — {g.get('place')}")
    if not ctx.get("foreign_news") and not ctx.get("gdelt_hotspots"):
        lines.append("- No international headlines in the current slice.")

    lines += ["", "## What to Watch Next", ""]
    for w in _normalize_watch_items(prose.get("what_to_watch") or ""):
        lines.append(f"- {w}")
    if not _normalize_watch_items(prose.get("what_to_watch") or ""):
        lines += [
            "- Flashpoints highlighted in the strategic risk brief (especially any marked critical).",
            "- Pathogens still marked rising on the wastewater rollup.",
            "- High-impact headlines in the domestic and international lists above.",
        ]

    prog = ctx.get("progression") if isinstance(ctx.get("progression"), dict) else {}
    prog_lines = list(prog.get("summary_lines") or [])
    prog_blurb = (prose.get("progression_blurb") or "").strip()
    lines += ["", "## 3-Day Progression", ""]
    if prog_blurb:
        lines += [prog_blurb, ""]
    if prog_lines:
        for ln in prog_lines:
            lines.append(f"- {ln}")
    else:
        lines.append("- No multi-day history yet (first run seeds the rolling JSON).")
    series = prog.get("series") or []
    if series:
        lines += ["", "| Date | Platform | Strategic | Pathogens ↑ | Mil. flights |", "|---|---|---|---:|---:|"]
        for s in series:
            lines.append(
                f"| {s.get('date')} | {s.get('platform_score')}/{s.get('platform_level')} | "
                f"{s.get('strategic_score')}/{s.get('strategic_level')} | "
                f"{s.get('pathogens_rising')} | {s.get('military_flights')} |"
            )

    lines += [
        "",
        "## Caveats",
        "",
        "This is an automated open-source digest. Coverage is incomplete, headlines can be noisy, "
        "and wastewater sampling typically lags real-time conditions by several days. "
        "It is not medical, legal, or operational advice — just a structured scan of public signals.",
    ]
    return "\n".join(lines)


# ── Render ──────────────────────────────────────────────────────────────────


def build_full_markdown(ctx: dict[str, Any], narrative_md: str) -> str:
    when = ctx["generated_at"]
    header = [
        "# PAT Labs Threat Assessment — Past 24 Hours",
        "",
        f"**Generated:** {when}  ",
        f"**Window:** {ctx.get('window')}  ",
        "",
        "---",
        "",
        narrative_md.strip(),
        "",
        "---",
        "",
        "## Source snapshot (structured)",
        "",
        f"- News items in feed: {ctx['source_counts'].get('news')}",
        f"- GDELT features: {ctx['source_counts'].get('gdelt')}",
        f"- Telegram OSINT items: {ctx['source_counts'].get('telegram')}",
        f"- Earthquakes in layer: {ctx['source_counts'].get('earthquakes')}",
        "",
    ]
    # Append compact factual tables for readers who want the raw bullets
    header += ["### Rising pathogens (data)", ""]
    rising = (ctx.get("wastewater") or {}).get("rising") or []
    if rising:
        header.append("| Pathogen | States rising | Sites rising | Sites alert | Δ rising rate |")
        header.append("|---|---:|---:|---:|---|")
        for p in rising:
            header.append(
                f"| {p.get('name')} | {p.get('states_rising')} | {p.get('sites_rising')} | "
                f"{p.get('sites_alert')} | {p.get('rising_rate_display') or 'n/a'} |"
            )
    else:
        header.append("_No rising pathogens in current rollup._")
    header += ["", "### Headlines (data)", ""]
    header.append("**Domestic**")
    for n in (ctx.get("domestic_news") or [])[:10]:
        header.append(f"- {n.get('title')} — _{n.get('source')}_")
    header.append("")
    header.append("**International**")
    for n in (ctx.get("foreign_news") or [])[:12]:
        header.append(f"- {n.get('title')} — _{n.get('source')}_")
    header += ["", ""]
    return "\n".join(header)


def _normalize_watch_items(watch: str | list | Any) -> list[str]:
    """Normalize Ollama what_to_watch (string, JSON list string, or list)."""
    if isinstance(watch, list):
        return [str(x).strip() for x in watch if str(x).strip()]
    text = str(watch or "").strip()
    if not text:
        return []
    # Python/JSON list as string: "['a', 'b']"
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        # ast-free fallback: split quoted segments
        parts = re.findall(r"['\"]([^'\"]+)['\"]", text)
        if parts:
            return [p.strip() for p in parts if p.strip()]
    if "\n" in text:
        out = []
        for w in text.splitlines():
            w = re.sub(r"^\s*[-*\d.)]+\s*", "", w).strip()
            if w:
                out.append(w)
        return out
    # comma-separated short items, else one blob
    if text.count(",") >= 2 and len(text) < 400:
        return [p.strip() for p in text.split(",") if p.strip()]
    return [text]


def _md_section_body(md: str, heading: str) -> str:
    """Return text under ## heading until next ##."""
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, md)
    return (m.group(1).strip() if m else "")


def _md_bullets(section_body: str) -> list[str]:
    bullets: list[str] = []
    for line in section_body.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            bullets.append(s[2:].strip())
    return bullets


def _md_paragraphs(section_body: str) -> list[str]:
    """Non-bullet prose blocks in a section."""
    chunks: list[str] = []
    buf: list[str] = []
    for line in section_body.splitlines():
        s = line.strip()
        if not s or s.startswith(("- ", "* ", "|", "```", "_")):
            if buf:
                chunks.append(" ".join(buf))
                buf = []
            continue
        # skip pure markdown emphasis-only notes later
        buf.append(s)
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def _inline_md(text: str) -> str:
    """Escape + light **bold** / highlight numbers for exec summary."""
    # Protect **strong** then escape
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        parts.append(html.escape(text[last : m.start()]))
        parts.append(f"<strong>{html.escape(m.group(1))}</strong>")
        last = m.end()
    parts.append(html.escape(text[last:]))
    out = "".join(parts)
    # Highlight standalone risk scores like "score of 36" first occurrence of bare number after "score"
    out = re.sub(
        r"(score of\s+)(\d{1,3})",
        r'\1<span class="highlight">\2</span>',
        out,
        count=1,
        flags=re.I,
    )
    return out


def _li(text: str) -> str:
    """Bullet with light bold markers for key prefixes."""
    raw = text.strip()
    if "**" in raw:
        t = _inline_md(raw)
    else:
        t = html.escape(raw)
        t = re.sub(r"^(Priority\s+\d+)\b", r"<strong>\1</strong>", t)
        t = re.sub(r"\b(\d+\s+CRITICAL-tier)\b", r"<strong>\1</strong>", t, flags=re.I)
        t = re.sub(r"\b(Overall Risk:\s*\w+)\b", r"<strong>\1</strong>", t, flags=re.I)
    return f"<li>{t}</li>"


def _rate_style(rate_display: Any) -> str:
    s = str(rate_display or "").strip()
    if s.startswith("+"):
        return ' style="color:#ef4444"'
    if s.startswith("-") and s not in {"-", "—", "n/a"}:
        return ' style="color:#10b981"'
    return ""


def _format_generated_local(iso_ts: str) -> str:
    """Human timestamp for meta line."""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        else:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M %Z")
    except ValueError:
        return iso_ts


def _format_snapshot_date(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return _now_local().strftime("%B %d, %Y")


def _render_progression_html(ctx: dict[str, Any]) -> str:
    """Email-safe 3-day progression table + change bullets."""
    prog = ctx.get("progression") if isinstance(ctx.get("progression"), dict) else {}
    series = list(prog.get("series") or [])
    summary = list(prog.get("summary_lines") or [])
    blurb = ""
    # progression_blurb lives in narrative section; optional on ctx
    if isinstance(ctx.get("progression_blurb"), str):
        blurb = ctx["progression_blurb"].strip()

    def esc(s: Any) -> str:
        return html.escape("" if s is None else str(s))

    parts: list[str] = []
    if blurb:
        parts.append(
            f'<p style="margin:0 0 10px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
            f'font-size:13px;color:#334155;line-height:1.5;">{esc(blurb)}</p>'
        )

    if series:
        rows = []
        for s in series:
            plat = s.get("platform_score")
            plat_l = s.get("platform_level") or "—"
            strat = s.get("strategic_score")
            strat_l = s.get("strategic_level") or "—"
            plat_cell = f"{plat}/{plat_l}" if plat is not None else str(plat_l)
            strat_cell = f"{strat}/{strat_l}" if strat is not None else str(strat_l)
            rows.append(
                "<tr>"
                f'<td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#0f172a;">{esc(s.get("date"))}</td>'
                f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;font-weight:700;color:#0f172a;">{esc(plat_cell)}</td>'
                f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#0f172a;">{esc(strat_cell)}</td>'
                f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#0f172a;">{esc(s.get("pathogens_rising") if s.get("pathogens_rising") is not None else "—")}</td>'
                f'<td align="center" style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#0f172a;">{esc(s.get("military_flights") if s.get("military_flights") is not None else "—")}</td>'
                "</tr>"
            )
        parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border:1px solid #e2e8f0;margin-bottom:10px;">'
            '<tr style="background:#f8fafc;">'
            '<th align="left" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Date</th>'
            '<th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Platform</th>'
            '<th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Strategic</th>'
            '<th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Path ↑</th>'
            '<th align="center" style="padding:8px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Flights</th>'
            "</tr>"
            + "".join(rows)
            + "</table>"
        )

    # Change bullets (skip the score trail line if table already shows it)
    change_lines = [ln for ln in summary if not str(ln).startswith("Score trail:")]
    if change_lines:
        lis = "".join(
            f'<tr><td width="14" valign="top" style="padding:4px 0;font-size:11px;color:#94a3b8;">•</td>'
            f'<td style="padding:4px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#334155;line-height:1.4;">{esc(ln)}</td></tr>'
            for ln in change_lines[:10]
        )
        parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{lis}</table>'
        )
    elif not series:
        parts.append(
            '<p style="margin:0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#64748b;">'
            "No multi-day history yet — this run seeds the rolling 3-day JSON."
            "</p>"
        )

    return "\n".join(parts) if parts else ""


def render_pat_labs_html(ctx: dict[str, Any], narrative_md: str) -> str:
    """Email-safe executive intelligence briefing (table layout for Outlook/Gmail)."""
    when = str(ctx.get("generated_at") or _now_local().isoformat(timespec="seconds"))
    title_date = _format_snapshot_date(when)
    gen_disp = _format_generated_local(when)
    title = f"PAT Labs Daily Threat Assessment — {title_date}"

    tl = ctx.get("threat_level") if isinstance(ctx.get("threat_level"), dict) else {}
    level = str(tl.get("level") or "n/a").upper()
    try:
        score = int(float(tl.get("score"))) if tl.get("score") is not None else None
    except (TypeError, ValueError):
        score = None
    drivers = [str(d) for d in (tl.get("drivers") or []) if d]

    threat_body = _md_section_body(narrative_md, "Threat Matrix")
    threat_bullets = [
        b for b in _md_bullets(threat_body)
        if not re.match(r"(?i)platform threat level\b", b)
    ]
    threat_blurb = " ".join(_md_paragraphs(threat_body)).strip()
    exec_body = _md_section_body(narrative_md, "Executive Summary")
    watch_body = _md_section_body(narrative_md, "What to Watch Next")
    caveats_body = _md_section_body(narrative_md, "Caveats")
    watch_items = _md_bullets(watch_body) or _normalize_watch_items(watch_body)
    watch_items = [w for w in watch_items if w and w not in {",", "—", "-"}]

    # ── Parse structured signals from delta / threat bullets ───────────────
    overall_risk = "—"
    trend = "—"
    critical_fps = "—"
    mil_flights = "—"
    for b in threat_bullets:
        m = re.search(r"(?i)overall risk:\s*(\w+)", b)
        if m:
            overall_risk = m.group(1).upper()
        m = re.search(r"(?i)trend:\s*(.+)$", b)
        if m:
            trend = m.group(1).strip()
        m = re.search(r"(?i)critical flashpoints:\s*(\d+)", b)
        if m:
            critical_fps = m.group(1)
        m = re.search(r"(?i)military flight[s]? (?:spike:\s*)?(\d+)", b)
        if m:
            mil_flights = m.group(1)

    # Delta assessment paragraph often embeds overall risk 65/100
    strategic_score = None
    for b in threat_bullets:
        m = re.search(r"(?i)elevated this cycle \((\d+)/100", b)
        if m:
            strategic_score = int(m.group(1))
        m = re.search(r"(?i)largest deteriorations:\s*([^.]+)", b)
        # keep for takeaways

    # Priority flashpoint cards
    priorities: list[dict[str, str]] = []
    for b in threat_bullets:
        m = re.search(
            r"(?i)priority\s+(\d+)\s*[·•\-]\s*(?:⛔|⚠|⚠️)?\s*(.+?)(?:\s*\[([^\]]*)\])?\s*$",
            b,
        )
        if not m:
            continue
        rank, region, delta = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
        # Band from emoji / rank
        band = "CRITICAL" if "⛔" in b or int(rank) <= 3 else "WATCH"
        if "⚠" in b or "⚠️" in b:
            band = "WATCH"
        rec = "Monitor closely"
        if band == "CRITICAL":
            rec = "Priority attention"
        if "▼" in delta or (delta.startswith("-") and delta not in {"-", "—"}):
            trend_txt = f"Deteriorating {delta}".strip()
            rec = "Elevated watch — deteriorating posture"
        elif "▲" in delta or delta.startswith("+"):
            trend_txt = f"Improving {delta}".strip()
            rec = "Track improvement"
        elif delta in {"—", "-", ""}:
            trend_txt = "Steady / unchanged"
        else:
            trend_txt = delta or "See assessment"
        priorities.append(
            {
                "rank": rank,
                "region": region,
                "band": band,
                "trend": trend_txt,
                "metric": delta or "—",
                "rec": rec,
                "note": b,
            }
        )

    ww = ctx.get("wastewater") if isinstance(ctx.get("wastewater"), dict) else {}
    rising = list(ww.get("rising") or [])
    # Sort rising by impact: sites_alert, then sites_rising
    def _rise_key(p: dict) -> tuple:
        try:
            return (
                -int(p.get("sites_alert") or 0),
                -int(p.get("sites_rising") or 0),
                str(p.get("name") or ""),
            )
        except (TypeError, ValueError):
            return (0, 0, str(p.get("name") or ""))

    rising_sorted = sorted([p for p in rising if isinstance(p, dict)], key=_rise_key)
    top_path = rising_sorted[0] if rising_sorted else None

    domestic = list(ctx.get("domestic_news") or [])
    foreign = list(ctx.get("foreign_news") or [])
    gdelt = list(ctx.get("gdelt_hotspots") or [])
    sc = ctx.get("source_counts") or {}

    # Domestic protest / alert signal
    domestic_alerts = 0
    for b in threat_bullets:
        if re.search(r"(?i)protest|domestic watch", b):
            domestic_alerts += 1
    for n in domestic:
        if re.search(r"(?i)protest|emergency|attack|shooting|nuclear|tariff|military", str(n.get("title") or "")):
            domestic_alerts += 1
    domestic_alerts = min(domestic_alerts, 9)

    # ── Posture colors (muted, email-safe) ─────────────────────────────────
    def _posture_colors(lvl: str) -> tuple[str, str, str]:
        """bg, border, text for level badge."""
        u = (lvl or "").upper()
        if u in {"CRITICAL", "SEVERE", "HIGH", "BLACK", "RED"}:
            return ("#fef2f2", "#fecaca", "#991b1b")
        if u in {"ELEVATED", "ORANGE", "ORANGE/WATCH"}:
            return ("#fff7ed", "#fed7aa", "#9a3412")
        if u in {"GUARDED", "YELLOW", "WATCH"}:
            return ("#fffbeb", "#fde68a", "#92400e")
        if u in {"LOW", "GREEN", "NORMAL"}:
            return ("#ecfdf5", "#a7f3d0", "#065f46")
        return ("#f1f5f9", "#cbd5e1", "#334155")

    # Platform vs strategic: show both in banner
    platform_level = level
    strategic_level = overall_risk if overall_risk != "—" else platform_level
    # Prefer strategic overall risk for primary banner if available
    primary_level = strategic_level if overall_risk != "—" else platform_level
    p_bg, p_bd, p_tx = _posture_colors(primary_level)
    # Trend display
    trend_disp = trend if trend != "—" else "→ Mixed / steady"
    if re.search(r"(?i)deterior|worsen|▼", trend_disp + " " + " ".join(threat_bullets[:8])):
        condition_word = "Conditions mixed — key theaters deteriorating"
    elif re.search(r"(?i)improv|▲", " ".join(threat_bullets[:12])):
        condition_word = "Mixed — some theaters improving"
    else:
        condition_word = "Mixed / steady"

    # ── Executive Snapshot bullets (from data only) ───────────────────────
    snapshot: list[str] = []
    if score is not None and overall_risk != "—":
        snapshot.append(
            f"Platform posture {platform_level} ({score}/100); strategic overall risk {overall_risk}"
            + (f" ({strategic_score}/100)" if strategic_score is not None else "")
            + f" — {trend_disp}."
        )
    elif score is not None:
        snapshot.append(f"Platform posture {platform_level} ({score}/100) — {trend_disp}.")
    else:
        snapshot.append(f"Platform posture {platform_level} — {trend_disp}.")

    if priorities:
        det = ", ".join(p["region"] for p in priorities[:3])
        snapshot.append(f"Priority flashpoints: {det}.")
    if top_path:
        snapshot.append(
            f"Biosecurity: {top_path.get('name')} leading rising pathogens "
            f"({top_path.get('states_rising')} states / {top_path.get('sites_rising')} sites, "
            f"{top_path.get('rising_rate_display') or 'n/a'}); "
            f"{ww.get('pathogens_rising') or len(rising_sorted)} pathogens rising overall."
        )
    if mil_flights != "—":
        snapshot.append(f"Military flight activity elevated: {mil_flights} tracked.")
    # One headline signal
    if domestic:
        t0 = domestic[0]
        snapshot.append(
            f"Domestic lead: {t0.get('title')}"
            + (f" ({t0.get('source')})" if t0.get("source") else "")
            + "."
        )
    elif foreign:
        t0 = foreign[0]
        snapshot.append(
            f"International lead: {t0.get('title')}"
            + (f" ({t0.get('source')})" if t0.get("source") else "")
            + "."
        )
    snapshot = snapshot[:5]

    # ── Top takeaways (5) ─────────────────────────────────────────────────
    takeaways: list[str] = []
    for p in priorities[:3]:
        takeaways.append(f"{p['region']} — {p['band'].title()} ({p['trend']})")
    if top_path:
        takeaways.append(
            f"{top_path.get('name')} expanding — {top_path.get('states_rising')} states rising "
            f"({top_path.get('rising_rate_display') or 'n/a'})"
        )
    if mil_flights != "—":
        takeaways.append(f"Military flights elevated — {mil_flights} tracked")
    for n in domestic[:2]:
        if len(takeaways) >= 5:
            break
        takeaways.append(str(n.get("title") or "")[:110])
    for n in foreign[:2]:
        if len(takeaways) >= 5:
            break
        takeaways.append(str(n.get("title") or "")[:110])
    takeaways = [t for t in takeaways if t][:5]

    # ── Categorize stories ────────────────────────────────────────────────
    cats: dict[str, list[str]] = {
        "Geopolitics": [],
        "Military": [],
        "Economics": [],
        "Technology": [],
        "Health": [],
        "Other": [],
    }

    def _categorize(title: str, source: str = "") -> str:
        blob = f"{title} {source}".lower()
        if re.search(r"ebola|pathogen|covid|virus|outbreak|wastewater|health|who\b|disease|hospital", blob):
            return "Health"
        if re.search(r"military|defence|defense|drone|missile|nato|war|army|flight|carrier|pentagon|strike|weapon", blob):
            return "Military"
        if re.search(r"tariff|dollar|yen|bank|market|trade|oil|economy|gdp|stock|power deal|openai", blob):
            return "Economics"
        if re.search(r"\bai\b|tech|cyber|satellite|space|chip|software|internet", blob):
            return "Technology"
        if re.search(r"nuclear|china|iran|ukraine|russia|taiwan|hormuz|saudi|gaza|israel|korea|xi\b|diplomat|border|sanctions", blob):
            return "Geopolitics"
        return "Other"

    all_stories: list[tuple[str, str, str]] = []
    for n in domestic + foreign:
        title_n = str(n.get("title") or "").strip()
        src = str(n.get("source") or "").strip()
        if not title_n:
            continue
        cat = _categorize(title_n, src)
        label = f"{title_n}" + (f" — {src}" if src else "")
        all_stories.append((cat, label, src))
    for g in gdelt[:5]:
        hl = str(g.get("headline") or "").strip()
        if not hl:
            continue
        place = str(g.get("place") or "").strip()
        label = f"{hl}" + (f" — {place}" if place else "")
        cat = _categorize(hl, place)
        all_stories.append((cat, label, place))

    # Cap per category for scanability; keep remainder countable
    for cat, label, _ in all_stories:
        if len(cats[cat]) < 5:
            cats[cat].append(label)
    # Drop empty categories from display order
    cat_order = ["Geopolitics", "Military", "Economics", "Technology", "Health", "Other"]

    # Significant domestic only
    sig_domestic: list[str] = []
    for n in domestic:
        title_n = str(n.get("title") or "").strip()
        if not title_n:
            continue
        if re.search(
            r"(?i)nuclear|military|tariff|border|attack|iran|china|xi|saudi|pentagon|defense|defence|protest|emergency",
            title_n,
        ) or True:
            # Prefer all domestic but cap at 6 — filter noise later
            sig_domestic.append(
                title_n + (f" — {n.get('source')}" if n.get("source") else "")
            )
    # Prefer higher-signal domestic
    sig_ranked = []
    for item in sig_domestic:
        weight = 0
        if re.search(r"(?i)nuclear|military|iran|china|saudi|tariff|defense|defence", item):
            weight += 2
        if re.search(r"(?i)protest|attack|emergency", item):
            weight += 1
        sig_ranked.append((weight, item))
    sig_ranked.sort(key=lambda x: -x[0])
    sig_domestic = [x[1] for x in sig_ranked[:6]]

    # Next 48h with why
    next48: list[tuple[str, str]] = []
    for p in priorities[:3]:
        why = "Theater remains on priority watch; posture change affects regional risk."
        if "Deteriorating" in p["trend"]:
            why = "Deteriorating deterrence elevates near-term escalation risk."
        next48.append((f"{p['region']} ({p['band'].title()})", why))
    if top_path:
        next48.append(
            (
                f"{top_path.get('name')} wastewater trend",
                f"Rising across {top_path.get('states_rising')} states — watch public-health bulletins; samples lag (~{ww.get('median_sample_age_days')} days).",
            )
        )
    for w in watch_items[:3]:
        if len(next48) >= 6:
            break
        # avoid dupes
        if any(w.lower() in a.lower() for a, _ in next48):
            continue
        next48.append((w, "Flagged from current open-source signals for continued monitoring."))

    # Action posture (derived, not invented score)
    if overall_risk in {"CRITICAL", "HIGH"} or primary_level in {"CRITICAL", "HIGH", "SEVERE"}:
        action = "ACTION: Elevated monitoring recommended — prioritize flashpoints below."
        action_bg, action_bd, action_tx = "#fef2f2", "#fecaca", "#991b1b"
    elif overall_risk == "ELEVATED" or primary_level in {"ELEVATED", "GUARDED"}:
        action = "ACTION: Routine elevated monitoring — no automatic operational change from this digest alone."
        action_bg, action_bd, action_tx = "#fffbeb", "#fde68a", "#92400e"
    else:
        action = "ACTION: Standard monitoring — review Priority Watch if conditions change."
        action_bg, action_bd, action_tx = "#f8fafc", "#e2e8f0", "#334155"

    # Caveats / methodology
    caveats = caveats_body or (
        "Automated open-source digest. Coverage is incomplete; headlines can be noisy; "
        "wastewater sampling typically lags real-time by several days. "
        "Not medical, legal, or operational advice."
    )
    caveats = re.sub(r"\s*—\s*just a structured scan of public signals\.?\s*$", "", caveats.strip())
    if not caveats.endswith("."):
        caveats += "."

    source_line = (
        f"News: {sc.get('news', 0)} · GDELT: {sc.get('gdelt', 0)} · "
        f"Telegram OSINT: {sc.get('telegram', 0)} · Earthquakes: {sc.get('earthquakes', 0)}"
    )

    # ── HTML helpers ──────────────────────────────────────────────────────
    def esc(s: Any) -> str:
        return html.escape("" if s is None else str(s))

    def metric_cell(label: str, value: str, sub: str = "") -> str:
        sub_html = (
            f'<div style="font-size:11px;color:#64748b;margin-top:4px;font-weight:400;">{esc(sub)}</div>'
            if sub
            else ""
        )
        return f"""
<td width="25%" valign="top" style="padding:8px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e2e8f0;border-radius:6px;background:#ffffff;">
    <tr><td style="padding:14px 12px;text-align:center;">
      <div style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-weight:600;">{esc(label)}</div>
      <div style="font-size:22px;font-weight:700;color:#0f172a;margin-top:6px;font-family:Segoe UI,Helvetica,Arial,sans-serif;line-height:1.2;">{esc(value)}</div>
      {sub_html}
    </td></tr>
  </table>
</td>"""

    # Metric values
    m_threat = f"{score}" if score is not None else "—"
    m_threat_sub = platform_level
    m_fp = critical_fps if critical_fps != "—" else str(len(priorities) or "—")
    m_mil = mil_flights
    m_path = str(ww.get("pathogens_rising") if ww.get("pathogens_rising") is not None else len(rising_sorted))
    m_dom = str(domestic_alerts)
    m_news = str(sc.get("news") or len(domestic) + len(foreign) or "—")
    m_eq = str(sc.get("earthquakes") or "—")

    # Snapshot list rows
    snap_rows = ""
    for i, s in enumerate(snapshot):
        snap_rows += f"""
<tr>
  <td width="22" valign="top" style="padding:6px 8px 6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#1e3a5f;font-weight:700;">▸</td>
  <td valign="top" style="padding:6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#0f172a;line-height:1.45;">{esc(s)}</td>
</tr>"""

    circ = ["①", "②", "③", "④", "⑤"]
    take_rows = ""
    for i, t in enumerate(takeaways):
        mark = circ[i] if i < len(circ) else f"{i+1}."
        take_rows += f"""
<tr>
  <td width="28" valign="top" style="padding:8px 10px 8px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;color:#1e3a5f;font-weight:700;">{mark}</td>
  <td valign="top" style="padding:8px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#0f172a;line-height:1.4;border-bottom:1px solid #f1f5f9;">{esc(t)}</td>
</tr>"""

    # Priority cards (2-col table)
    pri_html = ""
    if not priorities:
        pri_html = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td style="padding:12px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">No priority flashpoints extracted in this cycle.</td></tr>
</table>"""
    else:
        # pair cards
        rows_p = []
        for i in range(0, len(priorities), 2):
            chunk = priorities[i : i + 2]
            cells = []
            for p in chunk:
                bbg, bbd, btx = _posture_colors(p["band"])
                cells.append(f"""
<td width="50%" valign="top" style="padding:6px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e2e8f0;border-radius:6px;background:#fff;">
    <tr><td style="padding:14px 14px 12px 14px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#64748b;letter-spacing:0.05em;text-transform:uppercase;font-weight:600;">Priority {esc(p['rank'])}</td>
          <td align="right">
            <span style="display:inline-block;padding:3px 8px;border-radius:3px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.04em;background:{bbg};color:{btx};border:1px solid {bbd};">{esc(p['band'])}</span>
          </td>
        </tr>
      </table>
      <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:16px;font-weight:700;color:#0f172a;margin:8px 0 6px;">{esc(p['region'])}</div>
      <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#475569;margin-bottom:4px;"><strong>Trend:</strong> {esc(p['trend'])}</div>
      <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#475569;margin-bottom:4px;"><strong>Metric:</strong> {esc(p['metric'])}</div>
      <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#1e3a5f;margin-top:8px;padding-top:8px;border-top:1px solid #f1f5f9;"><strong>Recommendation:</strong> {esc(p['rec'])}</div>
    </td></tr>
  </table>
</td>""")
            if len(chunk) == 1:
                cells.append('<td width="50%" style="padding:6px;"></td>')
            rows_p.append("<tr>" + "".join(cells) + "</tr>")
        pri_html = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  {''.join(rows_p)}
</table>"""

    # Biosecurity pathogen rows — highlight meaningful increases
    path_rows = ""
    for p in rising_sorted:
        name = str(p.get("name") or "")
        rate = str(p.get("rising_rate_display") or "n/a")
        # emphasize if positive rate or high sites
        try:
            sites_alert = int(p.get("sites_alert") or 0)
            sites_rising = int(p.get("sites_rising") or 0)
        except (TypeError, ValueError):
            sites_alert, sites_rising = 0, 0
        emphasize = rate.startswith("+") or sites_alert >= 10
        name_style = "font-weight:700;color:#0f172a;" if emphasize else "font-weight:600;color:#334155;"
        rate_color = "#b91c1c" if rate.startswith("+") else ("#047857" if rate.startswith("-") else "#475569")
        path_rows += f"""
<tr>
  <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;{name_style}">{esc(name)}</td>
  <td align="center" style="padding:10px 8px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#0f172a;">{esc(p.get('states_rising'))}</td>
  <td align="center" style="padding:10px 8px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#0f172a;">{esc(p.get('sites_rising'))}</td>
  <td align="center" style="padding:10px 8px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#0f172a;">{esc(p.get('sites_alert'))}</td>
  <td align="right" style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;color:{rate_color};">{esc(rate)}</td>
</tr>"""

    if not path_rows:
        path_rows = """
<tr><td colspan="5" style="padding:12px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">No rising pathogens in current rollup.</td></tr>"""

    # Strategic developments by category
    strat_blocks = ""
    for cat in cat_order:
        items = cats.get(cat) or []
        if not items:
            continue
        lis = "".join(
            f'<tr><td width="14" valign="top" style="padding:5px 0;font-size:12px;color:#94a3b8;">•</td>'
            f'<td style="padding:5px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#1e293b;line-height:1.4;">{esc(it)}</td></tr>'
            for it in items
        )
        strat_blocks += f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;">
  <tr>
    <td style="padding:0 0 6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#1e3a5f;border-bottom:1px solid #e2e8f0;">
      {esc(cat)}
    </td>
  </tr>
  <tr><td style="padding-top:6px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{lis}</table>
  </td></tr>
</table>"""

    # Domestic block
    dom_rows = ""
    for it in sig_domestic:
        dom_rows += f"""
<tr>
  <td width="14" valign="top" style="padding:6px 0;font-size:12px;color:#94a3b8;">•</td>
  <td style="padding:6px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#1e293b;line-height:1.4;">{esc(it)}</td>
</tr>"""
    if not dom_rows:
        dom_rows = """
<tr><td style="padding:8px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">No significant domestic items in the current slice.</td></tr>"""

    # Next 48h
    n48_rows = ""
    for item, why in next48[:6]:
        n48_rows += f"""
<tr>
  <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;">
    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;font-weight:700;color:#0f172a;">{esc(item)}</div>
    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#64748b;margin-top:3px;line-height:1.4;"><span style="color:#1e3a5f;font-weight:600;">Why it matters:</span> {esc(why)}</div>
  </td>
</tr>"""

    # Full analysis (progressive disclosure — cleaned prose only)
    analysis_paras = ""
    exec_clean = _clean_exec_prose(exec_body) if exec_body else ""
    if not _exec_prose_ok(exec_clean):
        exec_clean = _fallback_executive_summary(ctx)
    for p in re.split(r"\n\s*\n", exec_clean):
        p = p.strip()
        if not p or re.match(r"^#{1,6}\s+", p):
            continue
        # Never show raw markdown markers in email
        p = re.sub(r"^#{1,6}\s+", "", p)
        p = re.sub(r"\*\*(.+?)\*\*", r"\1", p)
        analysis_paras += (
            f'<p style="margin:0 0 12px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
            f'font-size:13px;color:#334155;line-height:1.55;">{esc(p)}</p>'
        )
    if threat_blurb and threat_blurb not in exec_clean:
        tb = _clean_exec_prose(threat_blurb) or threat_blurb
        if tb and not re.match(r"^#{1,6}\s+", tb):
            analysis_paras += (
                f'<p style="margin:0 0 12px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
                f'font-size:13px;color:#334155;line-height:1.55;">{esc(tb)}</p>'
            )

    # Remaining threat context bullets (region shifts etc.) not in priority cards
    extra_context = []
    for b in threat_bullets:
        if re.search(r"(?i)priority\s+\d+", b):
            continue
        if re.search(r"(?i)overall risk:|trend:|critical flashpoints:|platform threat", b):
            continue
        extra_context.append(b)
    extra_rows = ""
    for b in extra_context[:12]:
        extra_rows += f"""
<tr>
  <td width="14" valign="top" style="padding:4px 0;font-size:11px;color:#94a3b8;">•</td>
  <td style="padding:4px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#475569;line-height:1.4;">{esc(b)}</td>
</tr>"""

    score_bar_w = max(0, min(100, score if score is not None else 0))

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<title>{esc(title)}</title>
<!--[if mso]>
<style type="text/css">
  body, table, td {{ font-family: Segoe UI, Helvetica, Arial, sans-serif !important; }}
</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#e8eef4;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    {esc(primary_level)} · {esc(condition_word)} · PAT Labs Daily Threat Assessment {esc(title_date)}
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#e8eef4;">
    <tr>
      <td align="center" style="padding:20px 12px;">

        <!-- Outer shell -->
        <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background-color:#ffffff;border:1px solid #d0d7de;">

          <!-- ===== TOP BANNER ===== -->
          <tr>
            <td style="background-color:#0b1f33;padding:0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="padding:18px 24px 8px 24px;">
                    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">
                      PAT Labs · Intelligence Briefing
                    </div>
                    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;color:#ffffff;margin-top:6px;letter-spacing:-0.02em;">
                      Daily Threat Assessment
                    </div>
                    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#8ba3b7;margin-top:4px;">
                      {esc(title_date)} · 24-hour window · Generated {esc(gen_disp)}
                    </div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 24px 18px 24px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#0f2740;border:1px solid #1e3a5f;">
                      <tr>
                        <td width="38%" style="padding:14px 16px;border-right:1px solid #1e3a5f;" valign="middle">
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">Overall Threat Level</div>
                          <div style="margin-top:6px;">
                            <span style="display:inline-block;padding:5px 10px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;font-weight:700;letter-spacing:0.04em;background:{p_bg};color:{p_tx};border:1px solid {p_bd};">{esc(primary_level)}</span>
                          </div>
                        </td>
                        <td width="32%" style="padding:14px 16px;border-right:1px solid #1e3a5f;" valign="middle">
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">Platform Score</div>
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:26px;font-weight:700;color:#ffffff;margin-top:4px;line-height:1;">
                            {esc(m_threat)}<span style="font-size:13px;font-weight:500;color:#8ba3b7;">/100</span>
                          </div>
                          <div style="margin-top:8px;height:4px;background:#1e3a5f;width:100%;">
                            <div style="height:4px;width:{score_bar_w}%;background:#3b82f6;font-size:0;line-height:0;">&nbsp;</div>
                          </div>
                        </td>
                        <td width="30%" style="padding:14px 16px;" valign="middle">
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:#8ba3b7;font-weight:600;">Trend</div>
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;font-weight:600;color:#e2e8f0;margin-top:6px;line-height:1.35;">
                            {esc(trend_disp)}
                          </div>
                          <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#8ba3b7;margin-top:4px;">
                            {esc(condition_word)}
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Action strip -->
          <tr>
            <td style="padding:0 24px;background:#ffffff;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;background:{action_bg};border:1px solid {action_bd};">
                <tr>
                  <td style="padding:10px 14px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;font-weight:600;color:{action_tx};letter-spacing:0.02em;">
                    {esc(action)}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- ===== EXECUTIVE SNAPSHOT ===== -->
          <tr>
            <td style="padding:22px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:10px;">
                Executive Snapshot
              </div>
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#64748b;margin-bottom:8px;">
                First-screen picture · entire brief in five lines
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                {snap_rows}
              </table>
            </td>
          </tr>

          <!-- ===== TOP TAKEAWAYS ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:4px;">
                Today&rsquo;s Top Takeaways
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                {take_rows}
              </table>
            </td>
          </tr>

          <!-- ===== QUICK METRICS ===== -->
          <tr>
            <td style="padding:18px 16px 8px 16px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin:0 8px 12px 8px;">
                Quick Metrics
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  {metric_cell("Threat Score", m_threat, m_threat_sub)}
                  {metric_cell("Flashpoints", m_fp, "critical / priority")}
                  {metric_cell("Mil. Flights", m_mil, "tracked")}
                  {metric_cell("Rising Pathogens", m_path, "wastewater")}
                </tr>
                <tr>
                  {metric_cell("Domestic Signals", m_dom, "elevated items")}
                  {metric_cell("Articles", m_news, "news slice")}
                  {metric_cell("GDELT", str(sc.get("gdelt") or "—"), "features")}
                  {metric_cell("Earthquakes", m_eq, "layer count")}
                </tr>
              </table>
            </td>
          </tr>

          <!-- ===== PRIORITY WATCH ===== -->
          <tr>
            <td style="padding:18px 16px 8px 16px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin:0 8px 10px 8px;">
                Priority Watch
              </div>
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#64748b;margin:0 8px 8px 8px;">
                Highest-priority theaters · posture, trend, recommendation
              </div>
              {pri_html}
            </td>
          </tr>

          <!-- ===== STRATEGIC CONTEXT (extra bullets) ===== -->
          {"<tr><td style='padding:8px 24px 8px 24px;'><div style='font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:1px solid #e2e8f0;padding-bottom:6px;margin-bottom:6px;'>Strategic Context</div><table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0'>" + extra_rows + "</table></td></tr>" if extra_rows else ""}

          <!-- ===== STRATEGIC DEVELOPMENTS ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:12px;">
                Strategic Developments
              </div>
              {strat_blocks if strat_blocks else '<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#64748b;">No categorized stories in this cycle.</div>'}
            </td>
          </tr>

          <!-- ===== BIOSECURITY ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:10px;">
                Biosecurity · Wastewater
              </div>
              <p style="margin:0 0 12px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;color:#334155;line-height:1.45;">
                Plants active: <strong>{esc(ww.get('plants_active'))}</strong> of {esc(ww.get('plants_monitored'))}
                · Pathogens rising: <strong>{esc(ww.get('pathogens_rising'))}</strong>
                · Latest collection: <strong>{esc(ww.get('latest_collection_date'))}</strong>
                · Median sample age: ~{esc(ww.get('median_sample_age_days'))} days
              </p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e2e8f0;">
                <tr style="background:#f8fafc;">
                  <th align="left" style="padding:10px 12px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Pathogen</th>
                  <th align="center" style="padding:10px 8px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">States</th>
                  <th align="center" style="padding:10px 8px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Sites ↑</th>
                  <th align="center" style="padding:10px 8px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Alert</th>
                  <th align="right" style="padding:10px 12px;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;">Δ Rate</th>
                </tr>
                {path_rows}
              </table>
              <p style="margin:10px 0 0 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#94a3b8;line-height:1.4;">
                Environmental surveillance only — not clinical diagnosis. Positive Δ rates and high alert-site counts are emphasized.
              </p>
            </td>
          </tr>

          <!-- ===== DOMESTIC ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:8px;">
                Domestic
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                {dom_rows}
              </table>
            </td>
          </tr>

          <!-- ===== 3-DAY PROGRESSION ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:4px;">
                3-Day Progression
              </div>
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#64748b;margin-bottom:8px;">
                Rolling history · how scores and priorities moved (not just today)
              </div>
              {_render_progression_html(ctx)}
            </td>
          </tr>

          <!-- ===== NEXT 48 HOURS ===== -->
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:2px solid #0b1f33;padding-bottom:8px;margin-bottom:4px;">
                Next 48 Hours
              </div>
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#64748b;margin-bottom:6px;">
                Forward look · why each item matters
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                {n48_rows}
              </table>
            </td>
          </tr>

          <!-- ===== FULL ASSESSMENT (progressive disclosure) ===== -->
          {"<tr><td style='padding:18px 24px 8px 24px;'><div style='font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#1e3a5f;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-bottom:10px;'>Full Assessment</div>" + analysis_paras + "</td></tr>" if analysis_paras else ""}

          <!-- ===== METHODOLOGY ===== -->
          <tr>
            <td style="padding:20px 24px 24px 24px;">
              <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:14px;margin-bottom:8px;">
                Methodology &amp; Sources
              </div>
              <p style="margin:0 0 8px 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#94a3b8;line-height:1.5;">
                {esc(caveats)}
              </p>
              <p style="margin:0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:11px;color:#94a3b8;line-height:1.5;">
                {esc(source_line)} · Plants {esc(ww.get('plants_active'))}/{esc(ww.get('plants_monitored'))} · Collection {esc(ww.get('latest_collection_date'))}
              </p>
              <p style="margin:14px 0 0 0;font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#cbd5e1;letter-spacing:0.06em;text-transform:uppercase;">
                PAT Labs · Daily Threat Assessment · Unclassified open-source
              </p>
            </td>
          </tr>

        </table>
        <!-- /shell -->

      </td>
    </tr>
  </table>
</body>
</html>
"""
def write_outputs(md: str, html_doc: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Always overwrite fixed names — never create timestamped siblings
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    try:
        OUT_MD.chmod(0o644)
        OUT_HTML.chmod(0o644)
    except OSError:
        pass
    return {"markdown": str(OUT_MD), "html": str(OUT_HTML)}


def send_email_html(html_doc: str, md: str, subject: str) -> bool:
    """Send HTML email if SMTP is configured. Prefers DAILY_BRIEF_SMTP_*, falls back to DELTA_REPORT_SMTP_*."""
    host = _env("DAILY_BRIEF_SMTP_HOST") or _env("DELTA_REPORT_SMTP_HOST")
    to_addr = _env("DAILY_BRIEF_SMTP_TO") or _env("DELTA_REPORT_SMTP_TO")
    if not host or not to_addr:
        return False
    port = int(_env("DAILY_BRIEF_SMTP_PORT") or _env("DELTA_REPORT_SMTP_PORT") or "587")
    user = _env("DAILY_BRIEF_SMTP_USER") or _env("DELTA_REPORT_SMTP_USER")
    password = _env("DAILY_BRIEF_SMTP_PASSWORD") or _env("DELTA_REPORT_SMTP_PASSWORD")
    from_addr = (
        _env("DAILY_BRIEF_SMTP_FROM")
        or _env("DELTA_REPORT_SMTP_FROM")
        or user
        or "shadowbroker@localhost"
    )
    use_tls = _env_bool("DAILY_BRIEF_SMTP_TLS", True)
    if _env("DELTA_REPORT_SMTP_TLS") and not _env("DAILY_BRIEF_SMTP_TLS"):
        use_tls = _env_bool("DELTA_REPORT_SMTP_TLS", True)

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
    parser = argparse.ArgumentParser(description="PAT Labs Threat Assessment 24h brief (fixed filenames)")
    parser.add_argument("--no-ollama", action="store_true", help="Skip Ollama; structured fallback only")
    parser.add_argument("--no-email", action="store_true", help="Do not attempt SMTP delivery")
    parser.add_argument("--email", action="store_true", help="Force email attempt when SMTP is configured")
    args = parser.parse_args()

    print(f"[info] collecting from {SB_BASE} …")
    ctx = collect_context()
    print(
        f"[info] news={ctx['source_counts'].get('news')} "
        f"gdelt={ctx['source_counts'].get('gdelt')} "
        f"ww_rising={ctx['wastewater'].get('pathogens_rising')} "
        f"delta={'yes' if ctx.get('delta_excerpt') else 'no'}"
    )

    # Rolling 3-day history (fixed JSON filename) — seed/update before narrative
    day_snap = build_day_snapshot(ctx)
    hist_doc = upsert_history(day_snap)
    progression = compute_progression(hist_doc)
    ctx["day_snapshot"] = day_snap
    ctx["history"] = hist_doc
    ctx["progression"] = progression
    print(
        f"[ok] history {HISTORY_JSON} "
        f"days={progression.get('days_available')}/{HISTORY_DAYS}"
    )

    prose: dict[str, str] = {}
    if not args.no_ollama:
        print(f"[info] Ollama model={OLLAMA_MODEL} (prose bits) …")
        prose = ollama_prose_bits(ctx)
        if prose.get("executive_summary"):
            print("[info] Ollama prose received")
        else:
            print("[warn] Ollama prose empty; structured text only", file=sys.stderr)
    if prose.get("progression_blurb"):
        ctx["progression_blurb"] = prose["progression_blurb"]
    narrative = assemble_narrative(ctx, prose)

    md = build_full_markdown(ctx, narrative)
    html_doc = render_pat_labs_html(ctx, narrative)
    paths = write_outputs(md, html_doc)
    print(f"[ok] wrote {paths['markdown']}")
    print(f"[ok] wrote {paths['html']}")
    print(f"[ok] wrote {HISTORY_JSON}")

    want_email = args.email or (
        not args.no_email and _env_bool("DAILY_BRIEF_EMAIL", False)
    )
    if want_email:
        send_email_html(
            html_doc,
            md,
            subject=f"[PAT Labs] Threat Assessment — past 24 hours — {_now_local().strftime('%Y-%m-%d')}",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
