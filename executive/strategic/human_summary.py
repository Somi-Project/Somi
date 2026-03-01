from __future__ import annotations

from typing import Any


def render_human_summary(artifact: dict[str, Any]) -> str:
    t = str(artifact.get("type") or "")
    if t == "strategic_analysis":
        rec = str(artifact.get("recommended_path") or "(needs clarification)")
        unknowns = list(artifact.get("unknowns") or [])
        return f"Strategic read: recommended path is '{rec}'." + (f" Open unknowns: {len(unknowns)}." if unknowns else "")
    if t == "tradeoff_evaluation":
        rec = str(artifact.get("recommendation") or "")
        risk = artifact.get("risk_score")
        effort = artifact.get("effort_score")
        return f"Tradeoff read: choose '{rec}' (risk={risk}, effort={effort})."
    if t == "plan_revision":
        op = str(artifact.get("original_plan_id") or "")
        return f"Plan revision ready for original plan '{op}'."
    if t == "plan_revision_missing_original":
        return str(artifact.get("message") or "Original plan ID needed before revision.")
    if t == "proposal_hint":
        intent = str(artifact.get("intent") or "other")
        return f"Next-step hint prepared (intent: {intent})."
    return "Strategic artifact prepared."
