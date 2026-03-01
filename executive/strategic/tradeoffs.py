from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any


@dataclass(frozen=True)
class ScoreBundle:
    impact_on_goals: list[dict[str, Any]]
    risk_score: int
    effort_score: int
    alignment_score: int
    confidence_score: int
    sensitivity_flag: bool
    strategic_debt_signal: str


def _clamp_i(v: int, low: int = 0, high: int = 10) -> int:
    return max(low, min(high, int(v)))


def _count_links(context_pack_v1: dict[str, Any], option: str) -> int:
    low = option.lower()
    hits = 0
    for proj in list(context_pack_v1.get("projects") or []):
        title = str(proj.get("title") or "").lower()
        if low and (low in title or any(tok and tok in title for tok in low.split())):
            hits += 1
    return hits


def compute_impact_on_goals(
    context_pack_v1: dict[str, Any],
    option_a: str,
    option_b: str,
    *,
    allowed_artifact_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    goals = list(context_pack_v1.get("confirmed_goals") or [])
    out: list[dict[str, Any]] = []
    for goal in goals:
        gid = str(goal.get("goal_id") or "")
        linked = set(str(x) for x in list(goal.get("linked_project_ids") or []))
        a_links = _count_links(context_pack_v1, option_a)
        b_links = _count_links(context_pack_v1, option_b)
        if linked:
            a_links += 1
            b_links += 1
        if a_links > b_links:
            impact = "option_a_positive"
        elif b_links > a_links:
            impact = "option_b_positive"
        else:
            impact = "neutral"
        evidence = [str(x) for x in list(allowed_artifact_ids or [])[:2]]
        out.append({"goal_id": gid, "impact": impact, "evidence_artifact_ids": evidence})
    return out


def compute_effort_score(context_pack_v1: dict[str, Any], option_a: str, option_b: str) -> int:
    projects = list(context_pack_v1.get("projects") or [])
    tasks_affected = sum(int(p.get("open_items") or 0) for p in projects)
    files_touched = sum(len(list(p.get("linked_item_ids") or [])) for p in projects)
    risks = len(list(context_pack_v1.get("patterns") or [])) + len(list(context_pack_v1.get("calendar_conflicts") or []))
    complexity = tasks_affected * 0.2 + files_touched * 0.05 + risks * 1.4 + (len(option_a.split()) + len(option_b.split())) * 0.2
    return _clamp_i(round(complexity))


def compute_risk_score(context_pack_v1: dict[str, Any], *, unknown_count: int, scope_breadth: int) -> int:
    dep_volatility = len(list(context_pack_v1.get("patterns") or []))
    conflict = len(list(context_pack_v1.get("calendar_conflicts") or []))
    security_signals = 1 if any("security" in str(p.get("description") or "").lower() for p in list(context_pack_v1.get("patterns") or [])) else 0
    base = security_signals * 2 + unknown_count * 1 + dep_volatility * 1 + conflict * 1 + scope_breadth * 0.5
    return _clamp_i(round(base))


def compute_scores(
    context_pack_v1: dict[str, Any],
    option_a: str,
    option_b: str,
    *,
    unknown_count: int = 0,
    allowed_artifact_ids: list[str] | None = None,
) -> ScoreBundle:
    impact = compute_impact_on_goals(
        context_pack_v1,
        option_a,
        option_b,
        allowed_artifact_ids=allowed_artifact_ids,
    )
    effort = compute_effort_score(context_pack_v1, option_a, option_b)
    risk = compute_risk_score(context_pack_v1, unknown_count=unknown_count, scope_breadth=max(1, len(list(context_pack_v1.get("projects") or []))))
    alignment = _clamp_i(sum(1 for row in impact if row.get("impact") == "option_a_positive") - sum(1 for row in impact if row.get("impact") == "option_b_positive") + 5)
    coverage = len(list(context_pack_v1.get("relevant_artifact_ids") or []))
    confidence = max(0, min(100, 100 - unknown_count * 12 + min(20, coverage)))
    sensitivity = abs(risk - effort) <= 1
    debt = "high" if risk >= 8 else ("moderate" if risk >= 5 else "low")
    return ScoreBundle(impact, risk, effort, alignment, confidence, sensitivity, debt)


def deterministic_artifact_id(prefix: str, *parts: str) -> str:
    digest = sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"
