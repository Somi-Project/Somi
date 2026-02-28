from __future__ import annotations

from typing import Any, Dict

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import LLMEnvelope


def _diff_summary(prev_steps: list[str], new_constraints: list[str]) -> str:
    return f"Kept {len(prev_steps)} prior steps; added {len(new_constraints)} new constraints."


def build_plan(*, query: str, route: str, envelope: LLMEnvelope, trigger_reason: Dict[str, Any] | None = None) -> Dict[str, Any]:
    steps = []
    for line in (envelope.answer_text or "").splitlines():
        ln = line.strip(" -•\t")
        if ln:
            steps.append(ln)
    if not steps:
        steps = [
            "Clarify objective and success criteria.",
            "Break objective into 3-5 actions.",
            "Schedule actions by priority and deadline.",
        ]
    content = {"objective": query[:300], "steps": steps[:8], "constraints": [], "risks": [], "extra_sections": []}
    return build_base(
        artifact_type="plan",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=[],
        confidence=0.74,
        metadata={"derived_from": "llm_response"},
        trigger_reason=trigger_reason,
    )


def build_plan_revision(
    *, query: str, route: str, previous_plan: Dict[str, Any], new_constraints: list[str], trigger_reason: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    prev_content = dict(previous_plan.get("content") or previous_plan.get("data") or {})
    prev_steps = [str(x).strip() for x in list(prev_content.get("steps") or []) if str(x).strip()]
    if not prev_steps:
        prev_steps = [
            "Clarify objective and success criteria.",
            "Break objective into 3-5 actions.",
            "Schedule actions by priority and deadline.",
        ]
    constraints = [str(x).strip() for x in list(prev_content.get("constraints") or []) if str(x).strip()]
    additions = [c for c in (new_constraints or []) if c]
    constraints.extend(additions)
    content = {
        "objective": str(prev_content.get("objective") or query)[:300],
        "steps": prev_steps[:8],
        "constraints": constraints[:8],
        "risks": list(prev_content.get("risks") or [])[:6],
        "extra_sections": list(prev_content.get("extra_sections") or [])[:6],
    }
    return build_base(
        artifact_type="plan",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=[],
        confidence=0.79,
        metadata={"derived_from": "plan_revision", "revises_artifact_id": str(previous_plan.get("artifact_id") or "")},
        trigger_reason=trigger_reason,
        revises_artifact_id=str(previous_plan.get("artifact_id") or ""),
        diff_summary=_diff_summary(prev_steps, additions),
    )
