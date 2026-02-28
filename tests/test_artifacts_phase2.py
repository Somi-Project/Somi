import math

from handlers.contracts.fact_distiller import FactDistiller
from handlers.contracts.intent import ArtifactIntentDetector
from handlers.contracts.orchestrator import build_artifact_for_intent, validate_and_render
from handlers.contracts.store import ArtifactStore


def test_meeting_summary_not_triggered_for_mitosis_question():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("what is mitosis?", "llm_only", has_doc=False)
    assert out.artifact_intent != "meeting_summary"


def test_meeting_summary_triggers_for_transcript_blob():
    d = ArtifactIntentDetector(threshold=0.75)
    prompt = """
09:00 Alice: Let's start.
09:01 Bob: We should ship by Friday.
09:03 Carol: Action items next.
"""
    out = d.detect(prompt, "llm_only", has_doc=False)
    assert out.artifact_intent == "meeting_summary"


def test_meeting_summary_parses_action_items_section():
    text = """
Attendees:
- Alice
- Bob
Action items:
- Alice: draft launch email by Friday
- Bob: prepare dashboard due next week
Decisions:
- Launch beta cohort
"""
    art = build_artifact_for_intent(
        artifact_intent="meeting_summary",
        query="summarize these meeting notes",
        route="llm_only",
        answer_text=text,
    )
    md = validate_and_render(art)
    assert art["artifact_type"] == "meeting_summary"
    assert len(art["content"]["action_items"]) >= 2
    assert all(isinstance(x, dict) and x.get("task") for x in art["content"]["action_items"])
    assert "# Meeting Summary" in md


def test_decision_matrix_triggers_for_help_me_decide_between_two_options():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("Help me decide between Option A and Option B for my project", "llm_only", has_doc=False)
    assert out.artifact_intent == "decision_matrix"


def test_decision_matrix_not_triggered_for_single_option():
    d = ArtifactIntentDetector(threshold=0.75)
    out = d.detect("help me decide about Option A", "llm_only", has_doc=False)
    assert out.artifact_intent != "decision_matrix"


def test_decision_matrix_parses_criteria_weights_and_matrix_complete():
    prompt = """
Help me decide between AWS and GCP.
Criteria:
- Cost 5
- Reliability 3
- Developer Experience 2
"""
    art = build_artifact_for_intent(
        artifact_intent="decision_matrix",
        query=prompt,
        route="llm_only",
        answer_text=prompt,
    )
    c = art["content"]
    assert len(c["options"]) >= 2
    assert len(c["criteria"]) >= 2
    wsum = sum(float(x["weight"]) for x in c["criteria"])
    assert math.isclose(wsum, 1.0, rel_tol=1e-3, abs_tol=1e-3)

    covered = {(s["option"], s["criterion"]) for s in c["scores"]}
    expected = {(o, cr["name"]) for o in c["options"] for cr in c["criteria"]}
    assert covered == expected
    validate_and_render(art)


def test_storage_record_includes_phase2_contract_fields(tmp_path):
    s = ArtifactStore(str(tmp_path / "artifacts"))
    artifact = {
        "artifact_id": "art_x",
        "artifact_type": "meeting_summary",
        "schema_version": 1,
        "content": {
            "title": "Weekly Sync",
            "date": None,
            "attendees": [],
            "summary": [],
            "decisions": [],
            "action_items": [],
            "risks_blockers": [],
            "extra_sections": [],
        },
        "input_fingerprint": "abc",
    }
    s.append("user_1", artifact)
    got = s.get_by_id("user_1", "art_x")
    assert got is not None
    assert got.get("session_id") == "user_1"
    assert got.get("timestamp")
    assert got.get("artifact_type") == "meeting_summary"
    assert got.get("contract_name") == "meeting_summary"
    assert int(got.get("contract_version")) >= 1
    assert isinstance(got.get("data"), dict)


def test_fact_distiller_no_writes_for_new_artifact_types(monkeypatch):
    distiller = FactDistiller()
    called = {"n": 0}

    def _count_add_facts(*args, **kwargs):
        called["n"] += 1
        return 0

    monkeypatch.setattr(distiller.researched, "add_facts", _count_add_facts)
    wrote_1 = distiller.distill_and_write({"artifact_type": "meeting_summary", "content": {}, "citations": []})
    wrote_2 = distiller.distill_and_write({"artifact_type": "decision_matrix", "content": {}, "citations": []})
    assert wrote_1 == 0
    assert wrote_2 == 0
    assert called["n"] == 0


def test_meeting_summary_does_not_trigger_for_generic_action_items_term():
    d = ArtifactIntentDetector(threshold=0.75)
    prompt = "Can you explain what action items are in project management and why they matter?"
    out = d.detect(prompt, "llm_only", has_doc=False)
    assert out.artifact_intent != "meeting_summary"


def test_decision_matrix_accepts_explicit_scores_and_bounds_them():
    prompt = """
Help me decide between A and B.
Criteria:
- Cost 2
- Reliability 1
A: Cost=5
A: Reliability=6
B: Cost=2
B: Reliability=1
"""
    art = build_artifact_for_intent(
        artifact_intent="decision_matrix",
        query=prompt,
        route="llm_only",
        answer_text=prompt,
    )
    for row in art["content"]["scores"]:
        assert 1 <= int(row["score"]) <= 5


def test_store_handles_non_integer_schema_version_alias(tmp_path):
    s = ArtifactStore(str(tmp_path / "artifacts"))
    artifact = {
        "artifact_id": "art_bad_schema",
        "artifact_type": "meeting_summary",
        "schema_version": "v1",
        "content": {
            "title": "Weekly Sync",
            "date": None,
            "attendees": [],
            "summary": [],
            "decisions": [],
            "action_items": [],
            "risks_blockers": [],
            "extra_sections": [],
        },
    }
    s.append("u2", artifact)
    got = s.get_by_id("u2", "art_bad_schema")
    assert got is not None
    assert int(got.get("contract_version")) >= 1
