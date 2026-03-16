from __future__ import annotations

from executive.strategic.policies import is_execution_phrase


def should_bypass_capulet(user_text: str) -> bool:
    return is_execution_phrase(user_text)


def detect_capulet_artifact_type(user_text: str) -> str | None:
    low = str(user_text or "").lower()
    if should_bypass_capulet(low):
        return None
    if any(x in low for x in ("revise", "update plan", "improve steps")):
        return "plan_revision"
    if any(x in low for x in (" vs ", " or ", "prioritize")):
        return "tradeoff_evaluation"
    if any(x in low for x in ("plan", "strategy", "approach")):
        return "strategic_analysis"
    if any(x in low for x in ("what next", "how proceed", "next step")):
        return "proposal_hint"
    return None
