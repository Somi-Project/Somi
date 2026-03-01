from __future__ import annotations

from typing import Any

from executive.strategic.tradeoffs import compute_scores, deterministic_artifact_id


def build_tradeoff_evaluation(*, context_pack_v1: dict[str, Any], option_a: str, option_b: str, allowed_artifact_ids: list[str], reasoning_summary: str = "") -> dict[str, Any]:
    allowed = [str(x) for x in allowed_artifact_ids][:15]
    scores = compute_scores(context_pack_v1, option_a, option_b, unknown_count=0, allowed_artifact_ids=allowed)
    recommendation = option_a if scores.risk_score <= scores.effort_score else option_b
    return {
        "type": "tradeoff_evaluation",
        "artifact_id": deterministic_artifact_id("te", option_a, option_b, "|".join(allowed)),
        "option_a": option_a,
        "option_b": option_b,
        "impact_on_goals": scores.impact_on_goals,
        "risk_score": scores.risk_score,
        "effort_score": scores.effort_score,
        "time_cost_estimate": "short" if scores.effort_score <= 3 else ("medium" if scores.effort_score <= 7 else "long"),
        "recommendation": recommendation,
        "reasoning_summary": reasoning_summary or f"Recommendation favors {recommendation} based on deterministic risk/effort and goal-link impact.",
        "alignment_score": scores.alignment_score,
        "sensitivity_flag": scores.sensitivity_flag,
        "strategic_debt_signal": scores.strategic_debt_signal,
        "confidence_score": scores.confidence_score,
        "no_autonomy": True,
    }
