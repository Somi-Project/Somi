from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from executive.strategic.json_contract import extract_json_block, retry_with_repair, validate_schema
from executive.strategic.plan_revision import build_plan_revision, build_plan_revision_missing_original
from executive.strategic.proposal_hint import build_proposal_hint
from executive.strategic.strategic_analysis import build_strategic_analysis
from executive.strategic.tradeoff_evaluation import build_tradeoff_evaluation
from executive.strategic.tradeoffs import deterministic_artifact_id


@dataclass
class PlannerConfig:
    temperature: float = 0.1
    max_allowed_artifacts: int = 15


class StrategicPlanner:
    def __init__(self, llm_call: Callable[[str, float], str] | None = None, repair_call: Callable[[str, str], str] | None = None, config: PlannerConfig | None = None):
        self.llm_call = llm_call
        self.repair_call = repair_call or (lambda prompt, _bad: "{}")
        self.config = config or PlannerConfig()

    def _structured_failure(self, artifact_type: str, errors: list[str]) -> dict[str, Any]:
        prefix = {"strategic_analysis": "sa", "tradeoff_evaluation": "te", "plan_revision": "pr", "proposal_hint": "ph"}.get(artifact_type, "sa")
        return {
            "type": artifact_type,
            "artifact_id": deterministic_artifact_id(prefix, artifact_type, "failure"),
            "error": "validation_failed",
            "errors": errors[:20],
            "no_autonomy": True,
        }

    def plan(
        self,
        *,
        user_text: str,
        context_pack_v1: dict[str, Any],
        allowed_artifact_ids: list[str],
        exists_fn: Callable[[str], bool],
        artifact_type: str,
        original_plan_id: str | None = None,
        option_a: str | None = None,
        option_b: str | None = None,
    ) -> dict[str, Any]:
        allowed = [str(x) for x in allowed_artifact_ids][: self.config.max_allowed_artifacts]
        allowed_set = set(allowed)

        if artifact_type == "strategic_analysis":
            out = build_strategic_analysis(user_text=user_text, context_pack_v1=context_pack_v1, allowed_artifact_ids=allowed)
        elif artifact_type == "tradeoff_evaluation":
            out = build_tradeoff_evaluation(
                context_pack_v1=context_pack_v1,
                option_a=option_a or "Option A",
                option_b=option_b or "Option B",
                allowed_artifact_ids=allowed,
            )
        elif artifact_type == "plan_revision":
            if not str(original_plan_id or "").strip():
                out = build_plan_revision_missing_original(user_text=user_text)
                ok, errs = validate_schema("plan_revision_missing_original", out, allowed_set, exists_fn)
                if not ok:
                    return self._structured_failure("plan_revision", errs)
                return out
            out = build_plan_revision(
                user_text=user_text,
                context_pack_v1=context_pack_v1,
                allowed_artifact_ids=allowed,
                original_plan_id=str(original_plan_id or ""),
            )
        elif artifact_type == "proposal_hint":
            out = build_proposal_hint(user_text=user_text, intent="other", target_artifact_ids=allowed[:3])
        else:
            return self._structured_failure("strategic_analysis", [f"unsupported_artifact_type:{artifact_type}"])

        # Optional single LLM formatting pass, plus one repair retry on invalid JSON.
        if self.llm_call is not None:
            prompt = f"Return only strict JSON for {artifact_type}. Keep keys unchanged.\nDraft:\n{out}"
            raw = self.llm_call(prompt, min(0.2, max(0.0, float(self.config.temperature))))
            try:
                llm_out = extract_json_block(raw)
                out = llm_out
            except Exception as exc:
                try:
                    out = retry_with_repair(self.repair_call, prompt, raw, [str(exc)])
                except Exception:
                    return self._structured_failure(artifact_type, ["invalid_json_after_single_repair"])

        ok, errs = validate_schema(artifact_type, out, allowed_set, exists_fn)
        if not ok:
            return self._structured_failure(artifact_type, errs)
        return out
