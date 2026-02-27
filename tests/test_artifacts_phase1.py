import pytest

from handlers.contracts.intent import ArtifactIntentDetector
from handlers.contracts.store import ArtifactStore
from handlers.contracts.orchestrator import ArtifactBuildError, build_artifact_for_intent, validate_and_render


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
