from __future__ import annotations

from typing import Any, Callable

from executive.strategic.policies import deep_scan_forbidden_keys


SEVERITY = {"low", "medium", "high", "critical"}
INTENTS = {"apply_patch", "run_tests", "refactor", "other"}


def _req(data: dict[str, Any], key: str, errs: list[str]) -> None:
    if key not in data:
        errs.append(f"missing:{key}")


def validate_no_autonomy(data: dict[str, Any]) -> list[str]:
    return [] if data.get("no_autonomy") is True else ["no_autonomy_must_be_true"]


def validate_strategic_analysis(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("type", "artifact_id", "context_artifact_ids", "clarifications", "assumptions", "unknowns", "options", "tradeoffs", "recommended_path", "risk_assessment", "no_autonomy"):
        _req(data, k, errs)
    if str(data.get("type")) != "strategic_analysis":
        errs.append("type_mismatch")
    if not str(data.get("artifact_id", "")).startswith("sa_"):
        errs.append("artifact_id_prefix")
    for opt in list(data.get("options") or []):
        ev = list((opt or {}).get("evidence_artifact_ids") or [])
        if not ev:
            errs.append("option_missing_evidence_artifact_ids")
    for tr in list(data.get("tradeoffs") or []):
        ev = list((tr or {}).get("evidence_artifact_ids") or [])
        if len(ev) < 2:
            errs.append("tradeoff_requires_at_least_2_evidence_artifact_ids")
    for r in list(data.get("risk_assessment") or []):
        sev = str((r or {}).get("severity") or "")
        if sev and sev not in SEVERITY:
            errs.append(f"risk_assessment_invalid_severity:{sev}")
    errs.extend(validate_no_autonomy(data))
    return errs


def validate_tradeoff_evaluation(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("type", "artifact_id", "option_a", "option_b", "impact_on_goals", "risk_score", "effort_score", "time_cost_estimate", "recommendation", "reasoning_summary", "no_autonomy"):
        _req(data, k, errs)
    if str(data.get("type")) != "tradeoff_evaluation":
        errs.append("type_mismatch")
    if not str(data.get("artifact_id", "")).startswith("te_"):
        errs.append("artifact_id_prefix")
    for score_key in ("risk_score", "effort_score"):
        val = data.get(score_key)
        if not isinstance(val, int) or val < 0 or val > 10:
            errs.append(f"invalid_score:{score_key}")
    errs.extend(validate_no_autonomy(data))
    return errs


def validate_plan_revision(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("type", "artifact_id", "original_plan_id", "improvements", "risk_changes", "diff_summary", "no_autonomy"):
        _req(data, k, errs)
    if str(data.get("type")) != "plan_revision":
        errs.append("type_mismatch")
    if not str(data.get("artifact_id", "")).startswith("pr_"):
        errs.append("artifact_id_prefix")
    if not str(data.get("original_plan_id") or "").strip():
        errs.append("missing_original_plan_id")
    errs.extend(validate_no_autonomy(data))
    return errs


def validate_proposal_hint(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("type", "artifact_id", "intent", "target_artifact_ids", "preconditions", "estimated_scope", "requires_user_phrase", "no_autonomy"):
        _req(data, k, errs)
    if str(data.get("type")) != "proposal_hint":
        errs.append("type_mismatch")
    if not str(data.get("artifact_id", "")).startswith("ph_"):
        errs.append("artifact_id_prefix")
    if str(data.get("intent") or "") not in INTENTS:
        errs.append("invalid_intent")
    if data.get("requires_user_phrase") != ["do it", "apply", "run"]:
        errs.append("requires_user_phrase_must_match")
    errs.extend(validate_no_autonomy(data))
    return errs


def validate_plan_revision_missing_original(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("type", "artifact_id", "message", "requested_field", "examples", "no_autonomy"):
        _req(data, k, errs)
    if str(data.get("type")) != "plan_revision_missing_original":
        errs.append("type_mismatch")
    if not str(data.get("artifact_id", "")).startswith("prm_"):
        errs.append("artifact_id_prefix")
    if str(data.get("requested_field") or "") != "original_plan_id":
        errs.append("requested_field_must_be_original_plan_id")
    errs.extend(validate_no_autonomy(data))
    return errs


def validate_artifact_references(data: dict[str, Any], allowed_ids: set[str], exists_fn: Callable[[str], bool]) -> list[str]:
    errs: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("artifact_ids") and isinstance(v, list):
                    for aid in v:
                        sid = str(aid)
                        if sid not in allowed_ids:
                            errs.append(f"artifact_not_allowed:{sid}")
                        elif not exists_fn(sid):
                            errs.append(f"artifact_not_found:{sid}")
                elif k.endswith("artifact_id") and isinstance(v, str) and k not in {"artifact_id", "original_plan_id"}:
                    sid = str(v)
                    if sid not in allowed_ids:
                        errs.append(f"artifact_not_allowed:{sid}")
                    elif not exists_fn(sid):
                        errs.append(f"artifact_not_found:{sid}")
                _walk(v)
        elif isinstance(node, list):
            for x in node:
                _walk(x)

    _walk(data)
    return errs


def validate_phase8_artifact(schema_name: str, data: dict[str, Any], *, allowed_ids: set[str], exists_fn: Callable[[str], bool]) -> tuple[bool, list[str]]:
    mapping = {
        "strategic_analysis": validate_strategic_analysis,
        "tradeoff_evaluation": validate_tradeoff_evaluation,
        "plan_revision": validate_plan_revision,
        "plan_revision_missing_original": validate_plan_revision_missing_original,
        "proposal_hint": validate_proposal_hint,
    }
    if schema_name not in mapping:
        return False, [f"unsupported_schema:{schema_name}"]
    errs = mapping[schema_name](data)
    errs.extend(validate_artifact_references(data, allowed_ids, exists_fn))
    errs.extend(deep_scan_forbidden_keys(data))
    return (len(errs) == 0, errs)
