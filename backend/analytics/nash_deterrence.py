"""Nash equilibrium / deterrence analysis for strategic flashpoints.

Classical 2x2 pure-strategy Nash plus a live deterrence score fused from
GT region risk, feed signal volume, and optional entity hints (ships/bases).
Self-hosted and offline — no external APIs.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults / presets
# ---------------------------------------------------------------------------

# Payoff cells are (row_player_payoff, col_player_payoff). Higher = preferred.
# Strategies: 0 = Cooperate / Status Quo, 1 = Escalate / Defect.

_DEFAULT_2X2 = [
    [(3.0, 3.0), (1.0, 4.0)],  # C,C | C,D
    [(4.0, 1.0), (2.0, 2.0)],  # D,C | D,D  — classic PD-ish
]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def nash_deterrence_enabled() -> bool:
    """Feature flag — defaults on when GT analytics is enabled."""
    raw = str(os.environ.get("NASH_DETERRENCE_ENABLED", "")).strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off"}
    try:
        from analytics.settings import gt_analytics_enabled

        return gt_analytics_enabled()
    except Exception:
        return False


FLASHPOINT_PRESETS: list[dict[str, Any]] = [
    {
        "id": "taiwan_strait",
        "label": "Taiwan Strait",
        "lat": 24.0,
        "lng": 119.5,
        "gt_regions": ["taiwan", "china", "united_states"],
        "row_actor": "PRC",
        "col_actor": "US / Taiwan",
        "row_strategies": ["Status Quo", "Escalate"],
        "col_strategies": ["Status Quo", "Escalate"],
        "payoffs": copy.deepcopy(_DEFAULT_2X2),
        "keywords": ["taiwan", "strait", "pla navy", "carrier", "adiz"],
    },
    {
        "id": "south_china_sea",
        "label": "South China Sea",
        "lat": 12.0,
        "lng": 114.0,
        "gt_regions": ["china", "philippines", "vietnam"],
        "row_actor": "PRC",
        "col_actor": "ASEAN claimants",
        "row_strategies": ["Restraint", "Assert"],
        "col_strategies": ["Restraint", "Assert"],
        "payoffs": copy.deepcopy(_DEFAULT_2X2),
        "keywords": ["south china sea", "spratly", "nine-dash", "militia"],
    },
    {
        "id": "strait_of_hormuz",
        "label": "Strait of Hormuz",
        "lat": 26.5,
        "lng": 56.5,
        "gt_regions": ["iran", "saudi_arabia", "united_arab_emirates"],
        "row_actor": "Iran",
        "col_actor": "US / Gulf",
        "row_strategies": ["Open transit", "Harass / close"],
        "col_strategies": ["Patrol", "Strike posture"],
        "payoffs": [
            [(4.0, 4.0), (1.0, 3.0)],
            [(2.0, 1.0), (0.0, 0.0)],
        ],
        "keywords": ["hormuz", "tanker", "iran navy", "strait", "oil"],
    },
    {
        "id": "ukraine_borders",
        "label": "Ukraine Borders",
        "lat": 48.5,
        "lng": 37.5,
        "gt_regions": ["ukraine", "russia", "poland"],
        "row_actor": "Russia",
        "col_actor": "Ukraine / NATO",
        "row_strategies": ["Freeze line", "Offensive"],
        "col_strategies": ["Hold", "Counter-offensive"],
        "payoffs": copy.deepcopy(_DEFAULT_2X2),
        "keywords": ["ukraine", "donbas", "kharkiv", "mobilization", "artillery"],
    },
    {
        "id": "korean_peninsula",
        "label": "Korean Peninsula",
        "lat": 38.0,
        "lng": 127.0,
        "gt_regions": ["north_korea", "south_korea", "united_states"],
        "row_actor": "DPRK",
        "col_actor": "ROK / US",
        "row_strategies": ["Deter", "Missile test"],
        "col_strategies": ["Deter", "Exercises"],
        "payoffs": copy.deepcopy(_DEFAULT_2X2),
        "keywords": ["dprk", "north korea", "icbm", "thaad", "dmz"],
    },
    {
        "id": "baltic_nato",
        "label": "Baltic / NATO Flank",
        "lat": 56.0,
        "lng": 24.0,
        "gt_regions": ["russia", "poland", "estonia", "latvia", "lithuania"],
        "row_actor": "Russia",
        "col_actor": "NATO",
        "row_strategies": ["Probe", "Escalate"],
        "col_strategies": ["Tripwire", "Reinforce"],
        "payoffs": copy.deepcopy(_DEFAULT_2X2),
        "keywords": ["baltic", "kaliningrad", "suwalki", "nato"],
    },
]


# ---------------------------------------------------------------------------
# Pure Nash solver (2x2 pure strategies)
# ---------------------------------------------------------------------------


def pure_nash_equilibria(payoffs: list[list[tuple[float, float]]]) -> list[tuple[int, int]]:
    """Return pure-strategy Nash equilibria as (row_idx, col_idx) pairs."""
    if not payoffs or not payoffs[0]:
        return []
    rows = len(payoffs)
    cols = len(payoffs[0])
    eqs: list[tuple[int, int]] = []
    for i in range(rows):
        for j in range(cols):
            row_pay = payoffs[i][j][0]
            col_pay = payoffs[i][j][1]
            row_best = all(row_pay >= payoffs[ii][j][0] for ii in range(rows))
            col_best = all(col_pay >= payoffs[i][jj][1] for jj in range(cols))
            if row_best and col_best:
                eqs.append((i, j))
    return eqs


def nash_stability_score(
    payoffs: list[list[tuple[float, float]]],
    current_row: int,
    current_col: int,
    equilibria: list[tuple[int, int]] | None = None,
) -> float:
    """
    0–100 score: 100 = play is pure Nash; lower = profitable deviation exists.

    Combines (1) whether current cell is equilibrium and (2) magnitude of
    best unilateral deviation incentives.
    """
    eqs = equilibria if equilibria is not None else pure_nash_equilibria(payoffs)
    if not payoffs:
        return 50.0
    rows = len(payoffs)
    cols = len(payoffs[0])
    current_row = max(0, min(rows - 1, current_row))
    current_col = max(0, min(cols - 1, current_col))

    on_eq = (current_row, current_col) in eqs
    row_pay = payoffs[current_row][current_col][0]
    col_pay = payoffs[current_row][current_col][1]
    best_row_dev = max((payoffs[i][current_col][0] for i in range(rows)), default=row_pay)
    best_col_dev = max((payoffs[current_row][j][1] for j in range(cols)), default=col_pay)
    row_gain = max(0.0, best_row_dev - row_pay)
    col_gain = max(0.0, best_col_dev - col_pay)
    # Scale gains: a gain of 2+ payoff points is "large"
    pressure = min(1.0, (row_gain + col_gain) / 4.0)
    if on_eq:
        score = 100.0 - pressure * 25.0
    else:
        score = 55.0 - pressure * 55.0
        if eqs:
            # Closer if same strategy as some equilibrium on one axis
            shared = any(e[0] == current_row or e[1] == current_col for e in eqs)
            if shared:
                score += 15.0
    return round(max(0.0, min(100.0, score)), 1)


def _normalize_payoffs(raw: Any) -> list[list[tuple[float, float]]]:
    """Accept nested lists of [r,c] pairs or tuples."""
    out: list[list[tuple[float, float]]] = []
    if not isinstance(raw, list):
        return copy.deepcopy(_DEFAULT_2X2)
    for row in raw:
        if not isinstance(row, list):
            continue
        out_row: list[tuple[float, float]] = []
        for cell in row:
            if isinstance(cell, (list, tuple)) and len(cell) >= 2:
                out_row.append((float(cell[0]), float(cell[1])))
            else:
                out_row.append((0.0, 0.0))
        if out_row:
            out.append(out_row)
    return out if out else copy.deepcopy(_DEFAULT_2X2)


# ---------------------------------------------------------------------------
# Live deterrence fusion from GT + feeds
# ---------------------------------------------------------------------------


def _region_gt_scores(gt_risk: dict[str, Any] | None, regions: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    features = ((gt_risk or {}).get("heatmap") or {}).get("features") or []
    wanted = {str(r).strip().lower() for r in regions if r}
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") or {}
        region = str(props.get("region") or "").strip().lower()
        if region not in wanted:
            continue
        risk = float(props.get("risk") or 0.0)
        conflict = float(props.get("conflict") or 0.0)
        unrest = float(props.get("unrest") or 0.0)
        scores[region] = max(risk, conflict * 0.9 + unrest * 0.1)
    return scores


def _feed_keyword_hits(
    telegram: dict[str, Any] | None,
    reddit: dict[str, Any] | None,
    keywords: list[str],
    limit_scan: int = 120,
) -> int:
    keys = [k.lower() for k in keywords if k]
    if not keys:
        return 0
    hits = 0
    for payload in (telegram, reddit):
        posts = list((payload or {}).get("posts") or [])[:limit_scan]
        for post in posts:
            if not isinstance(post, dict):
                continue
            text = " ".join(
                str(post.get(k) or "")
                for k in ("title", "description", "title_translated", "description_translated")
            ).lower()
            if any(k in text for k in keys):
                hits += 1
    return hits


def deterrence_strength(
    *,
    nash_score: float,
    gt_scores: dict[str, float],
    keyword_hits: int,
    entity_boost: float = 0.0,
) -> dict[str, Any]:
    """
    Deterrence strength 0–100.

    High GT conflict risk + many escalation keywords *weaken* deterrence.
    High Nash stability *strengthens* it. Entity boost (carriers nearby, etc.)
    can strengthen or weaken depending on sign.
    """
    avg_gt = sum(gt_scores.values()) / len(gt_scores) if gt_scores else 0.15
    max_gt = max(gt_scores.values()) if gt_scores else 0.15
    # Feed heat: 0 hits → 0, 10+ hits → 1
    feed_heat = min(1.0, keyword_hits / 10.0)
    # Base from Nash stability
    base = nash_score * 0.55
    # Penalize elevated GT risk
    risk_penalty = (avg_gt * 0.45 + max_gt * 0.55) * 45.0
    feed_penalty = feed_heat * 20.0
    entity = max(-15.0, min(15.0, entity_boost))
    strength = base - risk_penalty - feed_penalty + entity + 25.0
    strength = round(max(0.0, min(100.0, strength)), 1)
    if strength >= 65:
        band = "strong"
    elif strength >= 40:
        band = "contested"
    else:
        band = "fragile"
    return {
        "score": strength,
        "band": band,
        "avg_gt_risk": round(avg_gt, 4),
        "max_gt_risk": round(max_gt, 4),
        "keyword_hits": keyword_hits,
        "entity_boost": entity,
    }


def infer_current_strategies(
    payoffs: list[list[tuple[float, float]]],
    gt_scores: dict[str, float],
    keyword_hits: int,
) -> tuple[int, int]:
    """Heuristic: high risk / feed heat → escalate (strategy index 1)."""
    max_gt = max(gt_scores.values()) if gt_scores else 0.0
    escalate = max_gt >= 0.45 or keyword_hits >= 4
    idx = 1 if escalate else 0
    rows = max(1, len(payoffs))
    cols = max(1, len(payoffs[0]) if payoffs else 1)
    return (min(idx, rows - 1), min(idx, cols - 1))


# ---------------------------------------------------------------------------
# Flashpoint store (JSON persistence)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_flashpoints: list[dict[str, Any]] = []
_entity_hints: list[dict[str, Any]] = []  # recent map entity links

_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_PERSIST_FILE = os.path.join(_PERSIST_DIR, "nash_flashpoints.json")


def _ensure_dir() -> None:
    try:
        os.makedirs(_PERSIST_DIR, exist_ok=True)
    except OSError:
        pass


def _save() -> None:
    try:
        _ensure_dir()
        with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"flashpoints": _flashpoints, "entity_hints": _entity_hints[-50:]}, f, indent=2)
    except OSError as exc:
        logger.warning("Failed to persist nash flashpoints: %s", exc)


def _load() -> None:
    global _flashpoints, _entity_hints
    try:
        if os.path.exists(_PERSIST_FILE):
            with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _flashpoints = list(data.get("flashpoints") or [])
                _entity_hints = list(data.get("entity_hints") or [])
                return
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load nash flashpoints: %s", exc)
    # Seed presets
    now = datetime.now(timezone.utc).isoformat()
    _flashpoints = []
    for preset in FLASHPOINT_PRESETS:
        fp = copy.deepcopy(preset)
        fp["source"] = "preset"
        fp["created_at"] = now
        fp["updated_at"] = now
        fp["current_row"] = 0
        fp["current_col"] = 0
        fp["locked_strategies"] = False
        _flashpoints.append(fp)
    _save()


_load()


def list_flashpoints() -> list[dict[str, Any]]:
    with _lock:
        return [copy.deepcopy(fp) for fp in _flashpoints]


def get_flashpoint(fp_id: str) -> dict[str, Any] | None:
    with _lock:
        for fp in _flashpoints:
            if fp.get("id") == fp_id:
                return copy.deepcopy(fp)
    return None


def upsert_flashpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Create or update a flashpoint (custom or override preset)."""
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        fp_id = str(body.get("id") or "").strip() or str(uuid.uuid4())[:12]
        existing = next((f for f in _flashpoints if f.get("id") == fp_id), None)
        base = copy.deepcopy(existing) if existing else {
            "id": fp_id,
            "source": "user",
            "created_at": now,
            "row_strategies": ["Cooperate", "Escalate"],
            "col_strategies": ["Cooperate", "Escalate"],
            "payoffs": copy.deepcopy(_DEFAULT_2X2),
            "gt_regions": [],
            "keywords": [],
            "current_row": 0,
            "current_col": 0,
            "locked_strategies": False,
        }
        for key in (
            "label", "lat", "lng", "row_actor", "col_actor",
            "row_strategies", "col_strategies", "gt_regions", "keywords",
            "current_row", "current_col", "locked_strategies",
        ):
            if key in body and body[key] is not None:
                base[key] = body[key]
        if "payoffs" in body and body["payoffs"] is not None:
            base["payoffs"] = _normalize_payoffs(body["payoffs"])
        else:
            base["payoffs"] = _normalize_payoffs(base.get("payoffs"))
        base["id"] = fp_id
        base["updated_at"] = now
        if existing is None:
            _flashpoints.append(base)
        else:
            for i, f in enumerate(_flashpoints):
                if f.get("id") == fp_id:
                    _flashpoints[i] = base
                    break
        _save()
        return copy.deepcopy(base)


def delete_flashpoint(fp_id: str) -> bool:
    with _lock:
        before = len(_flashpoints)
        _flashpoints[:] = [f for f in _flashpoints if f.get("id") != fp_id]
        if len(_flashpoints) < before:
            _save()
            return True
        return False


def reset_presets() -> list[dict[str, Any]]:
    """Wipe custom flashpoints and re-seed presets."""
    global _flashpoints
    with _lock:
        _flashpoints = []
        _load()
        return [copy.deepcopy(fp) for fp in _flashpoints]


def record_entity_hint(
    *,
    entity_type: str,
    entity_id: str,
    label: str,
    lat: float,
    lng: float,
    flashpoint_id: str = "",
) -> dict[str, Any]:
    """Link a map entity click to deterrence analysis."""
    hint = {
        "id": str(uuid.uuid4())[:10],
        "entity_type": str(entity_type or "")[:50],
        "entity_id": str(entity_id or "")[:100],
        "label": str(label or "")[:200],
        "lat": float(lat),
        "lng": float(lng),
        "flashpoint_id": str(flashpoint_id or ""),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        # Auto-attach nearest flashpoint if none specified
        if not hint["flashpoint_id"] and _flashpoints:
            best_id = ""
            best_d = 1e18
            for fp in _flashpoints:
                try:
                    dlat = float(fp.get("lat") or 0) - hint["lat"]
                    dlng = float(fp.get("lng") or 0) - hint["lng"]
                    dist = dlat * dlat + dlng * dlng
                except (TypeError, ValueError):
                    continue
                if dist < best_d:
                    best_d = dist
                    best_id = str(fp.get("id") or "")
            # ~15 degrees squared threshold (~rough regional attach)
            if best_d < 225:
                hint["flashpoint_id"] = best_id
        _entity_hints.append(hint)
        _entity_hints[:] = _entity_hints[-50:]
        _save()
        return copy.deepcopy(hint)


def _entity_boost_for(fp_id: str) -> float:
    """Crude boost from recent entity links near this flashpoint."""
    with _lock:
        hints = [h for h in _entity_hints if h.get("flashpoint_id") == fp_id]
    if not hints:
        return 0.0
    # Ships/military presence nearby → mixed signal: slight deterrence + awareness
    boost = 0.0
    for h in hints[-10:]:
        et = str(h.get("entity_type") or "").lower()
        if et in {"ship", "military", "military_base", "tracked"}:
            boost += 1.5
        elif et in {"flight", "uav"}:
            boost += 0.8
    return min(12.0, boost)


def analyze_flashpoint(
    fp: dict[str, Any],
    *,
    gt_risk: dict[str, Any] | None = None,
    telegram: dict[str, Any] | None = None,
    reddit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full analysis payload for one flashpoint."""
    payoffs = _normalize_payoffs(fp.get("payoffs"))
    eqs = pure_nash_equilibria(payoffs)
    gt_scores = _region_gt_scores(gt_risk, list(fp.get("gt_regions") or []))
    hits = _feed_keyword_hits(telegram, reddit, list(fp.get("keywords") or []))

    if fp.get("locked_strategies"):
        cur_r = int(fp.get("current_row") or 0)
        cur_c = int(fp.get("current_col") or 0)
    else:
        cur_r, cur_c = infer_current_strategies(payoffs, gt_scores, hits)

    nash = nash_stability_score(payoffs, cur_r, cur_c, eqs)
    det = deterrence_strength(
        nash_score=nash,
        gt_scores=gt_scores,
        keyword_hits=hits,
        entity_boost=_entity_boost_for(str(fp.get("id") or "")),
    )

    # Arrow: preferred move from current toward nearest equilibrium
    arrow = {"from": [cur_r, cur_c], "to": [cur_r, cur_c], "label": "at_play"}
    if eqs and (cur_r, cur_c) not in eqs:
        # Pick equilibrium minimizing strategy distance
        target = min(eqs, key=lambda e: abs(e[0] - cur_r) + abs(e[1] - cur_c))
        arrow = {
            "from": [cur_r, cur_c],
            "to": [target[0], target[1]],
            "label": "toward_eq",
        }
    elif (cur_r, cur_c) in eqs:
        arrow["label"] = "equilibrium"

    return {
        "id": fp.get("id"),
        "label": fp.get("label"),
        "lat": fp.get("lat"),
        "lng": fp.get("lng"),
        "row_actor": fp.get("row_actor"),
        "col_actor": fp.get("col_actor"),
        "row_strategies": list(fp.get("row_strategies") or []),
        "col_strategies": list(fp.get("col_strategies") or []),
        "payoffs": [[list(cell) for cell in row] for row in payoffs],
        "equilibria": [[i, j] for i, j in eqs],
        "current_row": cur_r,
        "current_col": cur_c,
        "locked_strategies": bool(fp.get("locked_strategies")),
        "nash_score": nash,
        "nash_band": "stable" if nash >= 70 else ("watch" if nash >= 45 else "unstable"),
        "deterrence": det,
        "gt_scores": gt_scores,
        "keyword_hits": hits,
        "arrow": arrow,
        "source": fp.get("source"),
        "updated_at": fp.get("updated_at"),
    }


def build_strategic_analysis(
    *,
    gt_risk: dict[str, Any] | None = None,
    telegram: dict[str, Any] | None = None,
    reddit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dashboard snapshot for all flashpoints."""
    if not nash_deterrence_enabled():
        return {
            "enabled": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flashpoints": [],
            "message": "Nash / Deterrence analysis is disabled.",
        }
    with _lock:
        fps = [copy.deepcopy(f) for f in _flashpoints]
        hints = [copy.deepcopy(h) for h in _entity_hints[-20:]]

    analyzed = [
        analyze_flashpoint(fp, gt_risk=gt_risk, telegram=telegram, reddit=reddit)
        for fp in fps
    ]
    analyzed.sort(key=lambda a: (a.get("deterrence") or {}).get("score", 50))
    return {
        "enabled": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "flashpoints": analyzed,
        "entity_hints": hints,
        "flashpoint_count": len(analyzed),
        "fragile_count": sum(
            1 for a in analyzed if (a.get("deterrence") or {}).get("band") == "fragile"
        ),
        "unstable_count": sum(1 for a in analyzed if a.get("nash_band") == "unstable"),
    }
