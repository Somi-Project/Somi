from __future__ import annotations

from typing import Any, Dict

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import LLMEnvelope


def build_plan(*, query: str, route: str, envelope: LLMEnvelope) -> Dict[str, Any]:
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
    content = {
        "objective": query[:300],
        "steps": steps[:8],
        "constraints": [],
        "risks": [],
        "extra_sections": [],
    }
    return build_base(
        artifact_type="plan",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=[],
        confidence=0.74,
        metadata={"derived_from": "llm_response"},
    )
