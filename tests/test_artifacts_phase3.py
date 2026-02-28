import json

import pytest

from handlers.contracts.intent import ArtifactIntentDetector
from handlers.contracts.orchestrator import build_artifact_for_intent, validate_and_render
from handlers.contracts.schemas import validate_artifact
from handlers.contracts.store import ArtifactStore


def test_precedence_tiebreak_deterministic_for_meeting_vs_action_items():
    d = ArtifactIntentDetector(threshold=0.75)
    prompt = """
Action items:
- Alice: ship release notes
09:00 Bob: meeting started
09:10 Carol: end
"""
    out = d.detect(prompt, "llm_only", has_doc=False)
    assert out.artifact_intent == "meeting_summary"
    assert out.trigger_reason.get("tie_break")


def test_validation_failure_fallback_no_write(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    bad = {
        "artifact_type": "decision_matrix",
        "data": {
            "question": "q",
            "options": ["A", "B"],
            "criteria": [{"name": "cost", "weight": 0.1}, {"name": "speed", "weight": 0.1}],
            "scores": [],
            "totals": [],
            "recommendation": "",
            "sensitivity_notes": [],
            "extra_sections": [],
        },
    }
    with pytest.raises(ValueError):
        validate_artifact("decision_matrix", bad)
    assert store.get_last_by_type("u1", "decision_matrix") is None


def test_secret_redaction_on_write(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    art = {
        "artifact_id": "art_secret",
        "artifact_type": "plan",
        "content": {"objective": "Use sk-1234567890abcdefghijklmnop", "steps": ["Bearer abcdefghijklmnopqrstuvwx012345"]},
    }
    store.append("u1", art)
    got = store.get_by_id("u1", "art_secret")
    assert "[REDACTED]" in json.dumps(got)
    assert "Potential secret redacted" in (got.get("warnings") or [])


def test_action_items_trigger_and_structure():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("Extract action items from these notes", "llm_only", has_doc=False)
    assert out.artifact_intent == "action_items"


def test_action_items_no_heading_no_trigger():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("What is action item tracking in PM?", "llm_only", has_doc=False)
    assert out.artifact_intent != "action_items"


def test_status_update_trigger_with_headings_and_caps():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("Done:\n- A\nDoing:\n- B\nBlocked:\n- C", "llm_only", has_doc=False)
    assert out.artifact_intent == "status_update"
    art = build_artifact_for_intent(
        artifact_intent="status_update",
        query="write a status update",
        route="llm_only",
        answer_text="Done:\n" + "\n".join([f"- d{i}" for i in range(20)]),
    )
    assert len(art["data"]["done"]) <= 12
    validate_and_render(art)


def test_plan_revision_metadata_and_index_read(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    prev = build_artifact_for_intent(artifact_intent="plan", query="help me plan", route="llm_only", answer_text="- one")
    store.append("u1", prev)
    rev = build_artifact_for_intent(
        artifact_intent="plan",
        query="revise plan",
        route="llm_only",
        answer_text="",
        previous_plan=prev,
        new_constraints=["budget cap"],
    )
    store.append("u1", rev)
    got = store.get_last("u1", "plan")
    assert got is not None
    assert got.get("revises_artifact_id") == prev.get("artifact_id")
    assert got.get("diff_summary")


def test_store_get_by_id_works_with_offset_zero_index(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append("u1", {"artifact_id": "art_first", "artifact_type": "plan", "content": {"objective": "o", "steps": ["s"]}})
    got = store.get_by_id("u1", "art_first")
    assert got is not None
    assert got.get("artifact_id") == "art_first"


def test_normalize_envelope_tolerates_bad_confidence():
    from handlers.contracts.base import normalize_envelope

    out = normalize_envelope({"artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}, "confidence": "not-a-number"})
    assert out["confidence"] == 0.0


def test_action_items_triggers_for_spanish_heading():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("""Tareas:
- Ana: preparar reporte""", "llm_only", has_doc=False)
    assert out.artifact_intent == "action_items"


def test_status_update_triggers_for_spanish_headings_and_parses():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("""Hecho:
- a
Haciendo:
- b
Bloqueado:
- c""", "llm_only", has_doc=False)
    assert out.artifact_intent == "status_update"
    art = build_artifact_for_intent(
        artifact_intent="status_update",
        query="actualización de estado",
        route="llm_only",
        answer_text="""Hecho:
- entregado
Haciendo:
- pruebas
Bloqueado:
- entorno""",
    )
    assert art["data"]["done"] == ["entregado"]
    assert art["data"]["doing"] == ["pruebas"]
    assert art["data"]["blocked"] == ["entorno"]


def test_store_tolerates_mixed_schema_versions_and_historical_lines(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append("u1", {"artifact_id": "art_v1", "artifact_type": "plan", "schema_version": 1, "content": {"objective": "v1", "steps": ["a"]}})
    store.append("u1", {"artifact_id": "art_v3", "artifact_type": "plan", "schema_version": 3, "content": {"objective": "v3", "steps": ["b"]}})

    # Add malformed historical line directly; iterator should skip safely.
    p = tmp_path / "artifacts" / "u1.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write("{not-json}\n")

    got = store.get_last("u1", "plan")
    assert got is not None
    assert got.get("artifact_id") == "art_v3"


def test_index_rebuild_large_session(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    for i in range(300):
        store.append("u_big", {"artifact_id": f"art_{i}", "artifact_type": "plan", "content": {"objective": f"o{i}", "steps": ["s"]}})

    idx = tmp_path / "artifacts" / "u_big.index.json"
    if idx.exists():
        idx.unlink()

    got = store.get_last("u_big", "plan")
    assert got is not None
    assert got.get("artifact_id") == "art_299"
