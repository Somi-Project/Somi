import sys
import types

import pytest

from handlers.contracts.intent import ArtifactIntentDetector
from handlers.contracts.store import ArtifactStore
from handlers.contracts.orchestrator import ArtifactBuildError, build_artifact_for_intent, validate_and_render
from handlers.contracts.fact_distiller import FactDistiller
from handlers.routing import decide_route
from handlers.contracts.policy import apply_research_degrade_notice, should_force_research_websearch


def test_intent_detector_research_prefers_websearch():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("give me a synthesis with citations and sources", "websearch", has_doc=False)
    assert out.artifact_intent == "research_brief"
    assert out.confidence >= 0.75


def test_intent_detector_blocks_doc_extract_without_doc_context():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("extract from this document and include page refs", "llm_only", has_doc=False)
    assert out.artifact_intent is None


def test_store_append_and_retrieve(tmp_path):
    s = ArtifactStore(str(tmp_path / "artifacts"))
    obj = {
        "artifact_id": "art_123",
        "artifact_type": "plan",
        "content": {"objective": "x", "steps": ["a"]},
    }
    s.append("u1", obj)
    assert s.get_by_id("u1", "art_123")["artifact_type"] == "plan"
    assert s.get_last_by_type("u1", "plan")["artifact_id"] == "art_123"


def test_store_sanitizes_session_ids(tmp_path):
    s = ArtifactStore(str(tmp_path / "artifacts"))
    obj = {"artifact_id": "art_abc", "artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}}
    s.append("../../bad/session", obj)
    assert s.get_by_id("../../bad/session", "art_abc") is not None


def test_pipeline_and_render_research_brief():
    art = build_artifact_for_intent(
        artifact_intent="research_brief",
        query="compare options",
        route="websearch",
        answer_text="short answer",
        raw_search_results=[
            {"title": "A", "url": "https://a.com", "description": "finding a"},
            {"title": "B", "url": "https://b.com", "description": "finding b"},
            {"title": "C", "url": "https://c.com", "description": "finding c"},
        ],
    )
    md = validate_and_render(art)
    assert "# Research Brief" in md


def test_intent_detector_blocks_command_routes():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("help me plan this", "command", has_doc=False)
    assert out.artifact_intent is None
    assert out.reason.startswith("route_blocked:")


def test_intent_detector_short_prompts_do_not_trigger():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("plan", "llm_only", has_doc=False)
    assert out.artifact_intent is None
    assert out.reason == "too_short"


def test_intent_detector_smalltalk_does_not_trigger():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("hello", "llm_only", has_doc=False)
    assert out.artifact_intent is None
    assert out.reason in {"smalltalk", "too_short"}


def test_orchestrator_research_brief_requires_min_sources():
    with pytest.raises(ArtifactBuildError):
        build_artifact_for_intent(
            artifact_intent="research_brief",
            query="q",
            route="websearch",
            answer_text="answer",
            raw_search_results=[{"title": "A", "url": "https://a.com", "description": "d"}],
            min_sources=3,
        )


def test_orchestrator_doc_extract_requires_context():
    with pytest.raises(ArtifactBuildError):
        build_artifact_for_intent(
            artifact_intent="doc_extract",
            query="q",
            route="llm_only",
            answer_text="answer",
            rag_block="",
        )


def test_build_base_includes_timestamp_alias():
    from handlers.contracts.base import build_base

    art = build_base(
        artifact_type="plan",
        inputs={"user_query": "x", "route": "llm_only"},
        content={"objective": "x", "steps": ["a"]},
    )
    assert art.get("created_at")
    assert art.get("timestamp") == art.get("created_at")


def test_store_append_injects_session_and_timestamp(tmp_path):
    s = ArtifactStore(str(tmp_path / "artifacts"))
    obj = {"artifact_type": "plan", "created_at": "2024-01-01T00:00:00+00:00", "content": {"objective": "x", "steps": ["a"]}}
    s.append("u1", obj)
    last = s.get_last_by_type("u1", "plan")
    assert last is not None
    assert last.get("session_id") == "u1"
    assert last.get("timestamp") == "2024-01-01T00:00:00+00:00"
    assert last.get("artifact_id")


def test_orchestrator_plan_revision_uses_previous_plan():
    prev = {
        "artifact_id": "art_prev",
        "artifact_type": "plan",
        "content": {
            "objective": "Get fit",
            "steps": ["Walk", "Lift"],
            "constraints": ["No gym on Sundays"],
            "risks": [],
            "extra_sections": [],
        },
    }
    art = build_artifact_for_intent(
        artifact_intent="plan",
        query="update that plan to 2 hours/week",
        route="llm_only",
        answer_text="",
        previous_plan=prev,
        new_constraints=["Time budget: 2 hours per week."],
    )
    assert art["artifact_type"] == "plan"
    assert art["metadata"].get("derived_from") == "plan_revision"
    assert "Time budget: 2 hours per week." in art["content"].get("constraints", [])


def test_smoke_no_plan_misfire_steps_of_glycolysis():
    d = ArtifactIntentDetector(threshold=0.75)
    route = decide_route("steps of glycolysis").route
    out = d.detect("steps of glycolysis", route, has_doc=False)
    assert out.artifact_intent != "plan"


def test_smoke_no_doc_extract_misfire_summarize_this_no_doc():
    d = ArtifactIntentDetector(threshold=0.75)
    route = decide_route("summarize this").route
    out = d.detect("summarize this", route, has_doc=False)
    assert out.artifact_intent != "doc_extract"


def test_smoke_research_upgrade_flag_triggers_for_non_websearch_route():
    assert should_force_research_websearch("llm_only", "research_brief", enabled=True) is True
    assert should_force_research_websearch("websearch", "research_brief", enabled=True) is False


def test_smoke_research_degrade_safe_notice_without_fact_distill(monkeypatch):
    msg = apply_research_degrade_notice(
        "Normal answer",
        reason="insufficient_sources:1<3 | Web search unavailable",
        enabled=True,
    )
    assert "Normal answer" in msg
    assert "answered without citations" in msg

    distiller = FactDistiller()
    called = {"n": 0}

    def _count_add_facts(*args, **kwargs):
        called["n"] += 1
        return 0

    monkeypatch.setattr(distiller.researched, "add_facts", _count_add_facts)
    wrote = distiller.distill_and_write({"artifact_type": "plan", "content": {}, "citations": []})
    assert wrote == 0
    assert called["n"] == 0


def test_smoke_doc_facts_gate_blocks_without_page_refs(monkeypatch):
    distiller = FactDistiller()
    called = {"n": 0}

    def _count_add_facts(*args, **kwargs):
        called["n"] += 1
        return 0

    monkeypatch.setattr(distiller.researched, "add_facts", _count_add_facts)
    artifact = {
        "artifact_type": "doc_extract",
        "inputs": {"user_query": "extract obligations"},
        "content": {
            "table_extract": ["row1", "row2"],
            "page_refs": [],
        },
    }
    wrote = distiller.distill_and_write(artifact, require_doc_page_refs=True)
    assert wrote == 0
    assert called["n"] == 0


def test_smoke_plan_revision_references_previous_id():
    prev = {
        "artifact_id": "art_prev2",
        "artifact_type": "plan",
        "content": {
            "objective": "Ship project",
            "steps": ["Plan", "Build"],
            "constraints": [],
            "risks": [],
            "extra_sections": [],
        },
    }
    art = build_artifact_for_intent(
        artifact_intent="plan",
        query="update that plan to 2 hours/week",
        route="llm_only",
        answer_text="",
        previous_plan=prev,
        new_constraints=["Time budget: 2 hours per week."],
    )
    assert art["artifact_type"] == "plan"
    assert art["metadata"].get("revises_artifact_id") == "art_prev2"




def _import_assistant_agent_with_stubbed_ollama():
    if "ollama" not in sys.modules:
        sys.modules["ollama"] = types.SimpleNamespace(AsyncClient=type("AsyncClient", (), {}))
    try:
        from agents import AssistantAgent
    except ModuleNotFoundError as exc:
        pytest.skip(f"AssistantAgent dependencies unavailable in test env: {exc}")
    return AssistantAgent


def test_plan_revision_followup_requires_explicit_prior_reference(monkeypatch):
    AssistantAgent = _import_assistant_agent_with_stubbed_ollama()

    monkeypatch.setenv("LLM_BACKEND", "none")
    agent = AssistantAgent()
    assert agent._is_plan_revision_followup("update that plan to 2 hours/week") is True
    assert agent._is_plan_revision_followup("I need a plan to update my resume") is False


def test_get_plan_for_revision_ignores_new_plan_requests(monkeypatch, tmp_path):
    AssistantAgent = _import_assistant_agent_with_stubbed_ollama()
    from handlers.contracts.store import ArtifactStore

    monkeypatch.setenv("LLM_BACKEND", "none")
    agent = AssistantAgent()
    agent.artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    agent.artifact_store.append(
        "u1",
        {
            "artifact_id": "art_prev",
            "artifact_type": "plan",
            "created_at": "2099-01-01T00:00:00+00:00",
            "content": {"objective": "Old plan", "steps": ["a"]},
        },
    )

    assert agent._get_plan_for_revision("u1", "I need a plan to update my resume") is None
def test_distiller_research_only_distills_claims_with_citations(monkeypatch):
    distiller = FactDistiller()
    captured = {"facts": []}

    def _capture_add_facts(facts, domain="general"):
        captured["facts"] = list(facts or [])
        return len(captured["facts"])

    monkeypatch.setattr(distiller.researched, "add_facts", _capture_add_facts)
    artifact = {
        "artifact_type": "research_brief",
        "inputs": {"user_query": "research x"},
        "content": {"key_findings": ["claim1", "claim2", "claim3"]},
        "citations": [
            {"url": "https://a", "title": "A"},
            {"url": "", "title": "B"},
        ],
    }
    wrote = distiller.distill_and_write(artifact)
    assert wrote == 1
    assert len(captured["facts"]) == 1
    assert captured["facts"][0]["fact"] == "claim1"
