from __future__ import annotations

from typing import Any

from executive.strategic.tradeoffs import deterministic_artifact_id


def build_plan_revision(*, user_text: str, context_pack_v1: dict[str, Any], allowed_artifact_ids: list[str], original_plan_id: str) -> dict[str, Any]:
    allowed = [str(x) for x in allowed_artifact_ids][:15]
    return {
        "type": "plan_revision",
        "artifact_id": deterministic_artifact_id("pr", user_text, original_plan_id, "|".join(allowed)),
        "original_plan_id": str(original_plan_id),
        "improvements": [
            {
                "change": "Front-load the highest impact step and defer low-leverage tasks.",
                "evidence_artifact_ids": allowed[:2],
            }
        ],
        "risk_changes": [
            {
                "change": "Reduce schedule risk by sequencing dependencies first.",
                "evidence_artifact_ids": allowed[:2],
            }
        ],
        "diff_summary": "Reordered plan sequence for clearer dependency flow and lower execution risk.",
        "no_autonomy": True,
    }


def build_plan_revision_missing_original(*, user_text: str) -> dict[str, Any]:
    return {
        "type": "plan_revision_missing_original",
        "artifact_id": deterministic_artifact_id("prm", user_text, "missing_original"),
        "message": "I can revise the plan once you provide the original_plan_id (or reference the specific plan artifact).",
        "requested_field": "original_plan_id",
        "examples": ["art_abc123", "plan_42"],
        "no_autonomy": True,
    }
