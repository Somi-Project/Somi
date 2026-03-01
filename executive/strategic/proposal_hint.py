from __future__ import annotations

from executive.strategic.tradeoffs import deterministic_artifact_id


def build_proposal_hint(*, user_text: str, intent: str, target_artifact_ids: list[str]) -> dict:
    targets = [str(x) for x in target_artifact_ids][:15]
    return {
        "type": "proposal_hint",
        "artifact_id": deterministic_artifact_id("ph", user_text, intent, "|".join(targets)),
        "intent": intent if intent in {"apply_patch", "run_tests", "refactor", "other"} else "other",
        "target_artifact_ids": targets,
        "preconditions": ["Phase 5 approval required", "Capability gating must pass"],
        "estimated_scope": "small" if len(targets) <= 2 else "medium",
        "requires_user_phrase": ["do it", "apply", "run"],
        "no_autonomy": True,
    }
