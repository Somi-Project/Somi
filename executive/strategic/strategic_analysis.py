from __future__ import annotations

from typing import Any

from executive.strategic.tradeoffs import deterministic_artifact_id


def build_strategic_analysis(*, user_text: str, context_pack_v1: dict[str, Any], allowed_artifact_ids: list[str]) -> dict[str, Any]:
    allowed = [str(x) for x in allowed_artifact_ids][:15]
    options = []
    unknowns = []
    clarifications = []
    if not allowed:
        unknowns.append("No allowed artifacts provided for evidence-backed analysis.")
        clarifications.append("Please provide 2-3 relevant artifact IDs for grounded strategy.")
    else:
        options = [
            {
                "option": "Conservative path",
                "pros": ["Lower change risk", "Keeps current momentum"],
                "cons": ["Slower upside"],
                "evidence_artifact_ids": allowed[:2],
            },
            {
                "option": "Balanced path",
                "pros": ["Balances speed and stability"],
                "cons": ["Requires tighter prioritization"],
                "evidence_artifact_ids": allowed[:2],
            },
        ]

    return {
        "type": "strategic_analysis",
        "artifact_id": deterministic_artifact_id("sa", user_text, "|".join(allowed)),
        "context_artifact_ids": allowed,
        "clarifications": clarifications,
        "assumptions": ["Phase 7 context_pack_v1 is current.", "No execution is requested in this step."],
        "unknowns": unknowns,
        "options": options,
        "tradeoffs": ([{"tradeoff": "Speed vs maintainability", "evidence_artifact_ids": allowed[:2]}] if len(allowed) >= 2 else []),
        "recommended_path": ("Balanced path" if options else ""),
        "risk_assessment": [
            ({"risk": "Scope drift against top goals", "severity": "medium", "evidence_artifact_ids": allowed[:2]} if allowed else {"risk": "Insufficient evidence set", "severity": "low"}),
        ],
        "planning_horizon": "short",
        "no_autonomy": True,
    }
