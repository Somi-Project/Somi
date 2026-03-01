from __future__ import annotations

from executive.strategic.json_contract import extract_json_block
from executive.strategic.planner import StrategicPlanner
from executive.strategic.routing_adapter import detect_phase8_artifact_type
from executive.strategic.validators import validate_phase8_artifact
from executive.strategic.human_summary import render_human_summary
from executive.strategic.tradeoffs import compute_scores
from handlers.contracts.orchestrator import validate_and_render


def _ctx():
    return {
        "artifact_type": "context_pack_v1",
        "projects": [
            {"project_id": "proj_1", "title": "Improve API reliability", "open_items": 3, "linked_item_ids": ["file_a", "file_b"]},
            {"project_id": "proj_2", "title": "Security hardening", "open_items": 2, "linked_item_ids": ["file_c"]},
        ],
        "confirmed_goals": [{"goal_id": "goal_1", "linked_project_ids": ["proj_1"]}],
        "top_impacts": [{"evidence_artifact_ids": ["task_12", "plan_9"]}],
        "patterns": [{"description": "security dependency aging"}],
        "calendar_conflicts": [{"id": "c1"}],
        "relevant_artifact_ids": ["task_12", "plan_9", "proj_1"],
    }


def _exists(aid: str) -> bool:
    return aid in {"task_12", "plan_9", "proj_1", "orig_plan_1"}


def test_strategic_analysis_schema():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="How should I approach X?",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12", "plan_9", "proj_1"],
        exists_fn=_exists,
        artifact_type="strategic_analysis",
    )
    assert out["type"] == "strategic_analysis"
    assert out["artifact_id"].startswith("sa_")
    assert out["no_autonomy"] is True


def test_strategic_analysis_empty_evidence_is_consistent():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="How should I approach X?",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=[],
        exists_fn=lambda _x: False,
        artifact_type="strategic_analysis",
    )
    assert out["options"] == []
    assert out["recommended_path"] == ""


def test_tradeoff_requires_artifacts():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="A vs B?",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12", "plan_9", "proj_1"],
        exists_fn=_exists,
        artifact_type="strategic_analysis",
    )
    assert all(opt.get("evidence_artifact_ids") for opt in out["options"])
    assert all(len(t.get("evidence_artifact_ids") or []) >= 2 for t in out["tradeoffs"])


def test_plan_revision_references_original():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="Revise this plan",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12", "plan_9"],
        exists_fn=_exists,
        artifact_type="plan_revision",
        original_plan_id="orig_plan_1",
    )
    assert out["original_plan_id"] == "orig_plan_1"


def test_no_proposal_action_emitted():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="A vs B?",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12", "plan_9"],
        exists_fn=_exists,
        artifact_type="tradeoff_evaluation",
        option_a="A",
        option_b="B",
    )
    as_text = str(out)
    assert "proposal_action" not in as_text


def test_invalid_json_retry():
    calls = {"n": 0}

    def bad_llm(_prompt: str, _temp: float) -> str:
        calls["n"] += 1
        return "{not json"

    def repair(_prompt: str, _bad: str) -> str:
        return '{"type":"strategic_analysis","artifact_id":"sa_x","context_artifact_ids":[],"clarifications":[],"assumptions":[],"unknowns":[],"options":[],"tradeoffs":[],"recommended_path":"","risk_assessment":[],"no_autonomy":true}'

    planner = StrategicPlanner(llm_call=bad_llm, repair_call=repair)
    out = planner.plan(
        user_text="strategy",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=[],
        exists_fn=lambda _x: True,
        artifact_type="strategic_analysis",
    )
    assert out["type"] == "strategic_analysis"
    assert calls["n"] == 1


def test_artifact_reference_validation_reject_hallucinated_ids():
    def fake_llm(_prompt: str, _temp: float) -> str:
        return '{"type":"strategic_analysis","artifact_id":"sa_x","context_artifact_ids":["bad_1"],"clarifications":[],"assumptions":[],"unknowns":[],"options":[{"option":"o1","pros":[],"cons":[],"evidence_artifact_ids":["bad_1"]}],"tradeoffs":[{"tradeoff":"x","evidence_artifact_ids":["bad_1","bad_2"]}],"recommended_path":"o1","risk_assessment":[],"no_autonomy":true}'

    planner = StrategicPlanner(llm_call=fake_llm)
    out = planner.plan(
        user_text="strategy",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12"],
        exists_fn=_exists,
        artifact_type="strategic_analysis",
    )
    assert out.get("error") == "validation_failed"


def test_tradeoff_scores_deterministic():
    s1 = compute_scores(_ctx(), "A", "B", unknown_count=1, allowed_artifact_ids=["task_12", "plan_9"])
    s2 = compute_scores(_ctx(), "A", "B", unknown_count=1, allowed_artifact_ids=["task_12", "plan_9"])
    assert s1.risk_score == s2.risk_score
    assert s1.effort_score == s2.effort_score


def test_routing_does_not_intercept_execution_phrases():
    assert detect_phase8_artifact_type("Do it") is None
    assert detect_phase8_artifact_type("Apply this") is None
    assert detect_phase8_artifact_type("Run now") is None


def test_routing_does_not_false_match_substrings():
    assert detect_phase8_artifact_type("This appliance strategy is fine") == "strategic_analysis"
    assert detect_phase8_artifact_type("Please align runtime strategy") == "strategic_analysis"


def test_extract_json_block_markdown():
    out = extract_json_block("```json\n{\"a\":1}\n```")
    assert out == {"a": 1}


def test_unsupported_schema_returns_errors_not_keyerror():
    ok, errs = validate_phase8_artifact("unknown_schema", {}, allowed_ids=set(), exists_fn=lambda _x: True)
    assert ok is False
    assert any("unsupported_schema" in e for e in errs)


def test_routing_bypass_expanded_vocabulary():
    assert detect_phase8_artifact_type("execute this") is None
    assert detect_phase8_artifact_type("please proceed now") is None


def test_plan_revision_missing_original_template():
    planner = StrategicPlanner()
    out = planner.plan(
        user_text="revise this",
        context_pack_v1=_ctx(),
        allowed_artifact_ids=["task_12"],
        exists_fn=_exists,
        artifact_type="plan_revision",
        original_plan_id="",
    )
    assert out["type"] == "plan_revision_missing_original"
    assert out["requested_field"] == "original_plan_id"
    assert out["no_autonomy"] is True


def test_plan_revision_missing_original_validator():
    ok, errs = validate_phase8_artifact(
        "plan_revision_missing_original",
        {
            "type": "plan_revision_missing_original",
            "artifact_id": "prm_abc",
            "message": "Need original plan id",
            "requested_field": "original_plan_id",
            "examples": ["art_123"],
            "no_autonomy": True,
        },
        allowed_ids=set(),
        exists_fn=lambda _x: True,
    )
    assert ok is True
    assert errs == []


def test_human_summary_adapter_basic():
    art = {"type": "tradeoff_evaluation", "recommendation": "A", "risk_score": 2, "effort_score": 3}
    text = render_human_summary(art)
    assert "choose 'A'" in text


def test_plan_revision_missing_original_markdown_renderer():
    md = validate_and_render(
        {
            "contract_name": "plan_revision_missing_original",
            "artifact_type": "plan_revision_missing_original",
            "content": {
                "type": "plan_revision_missing_original",
                "artifact_id": "prm_abc",
                "message": "Need original plan id",
                "requested_field": "original_plan_id",
                "examples": ["art_123"],
                "no_autonomy": True,
            },
        }
    )
    assert "Plan Revision Needs Context" in md
    assert "original_plan_id" in md


def test_plan_revision_missing_original_markdown_renderer_rejects_bad_field():
    try:
        validate_and_render(
            {
                "contract_name": "plan_revision_missing_original",
                "artifact_type": "plan_revision_missing_original",
                "content": {
                    "type": "plan_revision_missing_original",
                    "artifact_id": "prm_abc",
                    "message": "Need original plan id",
                    "requested_field": "wrong_field",
                    "examples": ["art_123"],
                    "no_autonomy": True,
                },
            }
        )
        assert False, "expected validator failure"
    except ValueError:
        assert True
