import json

from handlers.continuity import build_task_state_from_artifact, choose_thread_id_for_request, derive_thread_id, maybe_emit_continuity_artifact, normalize_tags, score_continuity
from handlers.contracts.base import normalize_envelope
from handlers.contracts.schemas import validate_artifact
from handlers.contracts.store import ArtifactStore


def test_envelope_continuity_defaults_and_clamps():
    out = normalize_envelope({"artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}, "status": "bad", "continuity": {"resume_confidence": "nope"}})
    assert out["status"] == "unknown"
    assert out["continuity"]["no_autonomy"] is True
    assert out["continuity"]["resume_confidence"] == 0.0


def test_new_contract_validation_artifact_continuity_and_task_state():
    continuity = {
        "artifact_type": "artifact_continuity",
        "content": {
            "thread_id": "thr_1",
            "top_related_artifacts": [{"artifact_id": "a1", "type": "plan", "title": "t", "status": "open", "updated_at": "2024-01-01T00:00:00+00:00"}],
            "current_state_summary": "state",
            "suggested_next_steps": ["s1"],
            "assumptions": ["a"],
            "questions": [],
            "safety": {"no_autonomy": True, "no_execution": True},
        },
    }
    task_state = {
        "artifact_type": "task_state",
        "content": {
            "thread_id": "thr_1",
            "tasks": [{"task_id": "t1", "title": "do x", "status": "open", "owner": "a", "source_artifact_id": "art_1"}],
            "rollups": {"open_count": 1, "in_progress_count": 0, "done_count": 0, "blocked_count": 0},
            "suggested_updates": [{"task_id": "t1", "suggested_status": "in_progress", "reason": "started"}],
        },
    }
    assert validate_artifact("artifact_continuity", continuity)
    assert validate_artifact("task_state", task_state)


def test_thread_id_derivation_stable():
    assert derive_thread_id("Resume roadmap for OCR release") == derive_thread_id("Resume roadmap for OCR release")


def test_tag_normalization_rules():
    tags = normalize_tags([" OCR ", "OCR", "SecUrity", "a" * 40, "twitter", "secr$et"])
    assert tags == ["ocr", "security", "twitter", "secret"]


def test_confidence_scoring_thresholds():
    low = score_continuity(user_text="hello", ui_thread_id=None, tag_overlap=0.0, same_type=False, stale_90d=False)
    high = score_continuity(user_text="resume same thing", ui_thread_id="thr_x", tag_overlap=0.8, same_type=True, stale_90d=False)
    assert low < 0.55
    assert high >= 0.55


def test_linking_caps_and_related_ids():
    idx = {
        "recent_open_threads": [
            {
                "artifact_id": f"art_{i}",
                "thread_id": "thr_1",
                "type": "plan",
                "title": f"Plan {i}",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "status": "open",
                "tags": ["docs"],
            }
            for i in range(50)
        ]
    }
    res = maybe_emit_continuity_artifact("resume same thing", {"route": "llm_only", "tags": ["docs"]}, idx)
    assert res.artifact is not None
    assert len(res.artifact.get("related_artifact_ids") or []) <= 20
    assert len(res.artifact.get("data", {}).get("top_related_artifacts") or []) <= 10


def test_index_update_correctness_and_phase13_regression(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    # historical artifact without phase4 fields
    store.append("u1", {"artifact_id": "art_old", "artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}})
    # phase4 artifact with tags/thread/status
    store.append(
        "u1",
        {
            "artifact_id": "art_new",
            "artifact_type": "task_state",
            "thread_id": "thr_123",
            "status": "open",
            "tags": ["docs", "somi"],
            "content": {
                "thread_id": "thr_123",
                "tasks": [{"task_id": "t1", "title": "x", "status": "open", "owner": "u", "source_artifact_id": "art_old"}],
                "rollups": {"open_count": 1, "in_progress_count": 0, "done_count": 0, "blocked_count": 0},
                "suggested_updates": [],
            },
        },
    )
    snap = store.get_index_snapshot()
    assert "thr_123" in snap["by_thread_id"]
    assert "docs" in snap["by_tag"]
    assert "open" in snap["by_status"]
    assert store.get_by_id("u1", "art_old")["artifact_id"] == "art_old"


def test_stress_continuity_deterministic_return_windows():
    idx = {
        "recent_open_threads": [
            {
                "artifact_id": "art_a",
                "thread_id": "thr_a",
                "type": "plan",
                "title": "OCR deployment plan",
                "updated_at": "2026-02-01T00:00:00+00:00",
                "status": "open",
                "tags": ["ocr", "deployment"],
            },
            {
                "artifact_id": "art_b",
                "thread_id": "thr_b",
                "type": "task_state",
                "title": "Twitter bugfix checklist",
                "updated_at": "2025-12-01T00:00:00+00:00",
                "status": "in_progress",
                "tags": ["twitter", "bugfix"],
            },
        ]
    }
    prompts = ["resume same thing after 1 day", "resume same thing after 7 days", "resume same thing after 60 days", "resume maybe status"]
    first = [maybe_emit_continuity_artifact(p, {"route": "llm_only", "tags": ["ocr"]}, idx).artifact for p in prompts]
    second = [maybe_emit_continuity_artifact(p, {"route": "llm_only", "tags": ["ocr"]}, idx).artifact for p in prompts]

    def stable_projection(items):
        out = []
        for it in items:
            out.append(
                {
                    "thread_id": it.get("thread_id"),
                    "related": it.get("related_artifact_ids"),
                    "reasons": (it.get("continuity") or {}).get("resume_reasons"),
                    "suggested": (it.get("data") or {}).get("suggested_next_steps"),
                }
            )
        return out

    assert json.dumps(stable_projection(first), sort_keys=True) == json.dumps(stable_projection(second), sort_keys=True)


def test_candidate_ranking_uses_tag_index_pool():
    idx = {
        "recent_open_threads": [],
        "by_thread_id": {},
        "by_tag": {
            "ocr": [
                {
                    "artifact_id": "art_x",
                    "thread_id": "thr_x",
                    "type": "plan",
                    "title": "OCR pipeline",
                    "updated_at": "2026-02-01T00:00:00+00:00",
                    "status": "open",
                    "tags": ["ocr"],
                }
            ]
        },
    }
    res = maybe_emit_continuity_artifact("resume ocr", {"route": "llm_only", "tags": ["ocr"]}, idx)
    assert res.artifact is not None
    assert "art_x" in (res.artifact.get("related_artifact_ids") or [])


def test_thread_id_derivation_normalizes_resume_noise():
    a = derive_thread_id("Please resume the OCR deployment plan!!!")
    b = derive_thread_id("resume OCR deployment plan")
    assert a == b


def test_choose_thread_id_prefers_strong_existing_candidate():
    idx = {
        "recent_open_threads": [
            {
                "artifact_id": "art1",
                "thread_id": "thr_existing",
                "type": "plan",
                "title": "OCR deployment plan",
                "updated_at": "2026-02-01T00:00:00+00:00",
                "status": "open",
                "tags": ["ocr", "deployment"],
            }
        ],
        "by_thread_id": {},
        "by_tag": {"ocr": []},
    }
    tid = choose_thread_id_for_request("resume the ocr deployment plan", {"tags": ["ocr"], "thread_id": None, "artifact_intent": "plan"}, idx)
    assert tid == "thr_existing"


def test_task_state_carries_forward_prior_status_and_owner():
    source = {
        "artifact_id": "art_plan_2",
        "artifact_type": "plan",
        "content": {"steps": ["Ship docs", "Run tests"]},
    }
    prev = {
        "artifact_id": "art_ts_1",
        "artifact_type": "task_state",
        "thread_id": "thr_docs",
        "content": {
            "thread_id": "thr_docs",
            "tasks": [
                {"task_id": "tid_a", "title": "Ship docs", "status": "in_progress", "owner": "Sam", "source_artifact_id": "art_plan_1"}
            ],
            "rollups": {"open_count": 0, "in_progress_count": 1, "done_count": 0, "blocked_count": 0},
            "suggested_updates": [],
        },
    }
    out = build_task_state_from_artifact(source_artifact=source, thread_id="thr_docs", previous_task_state=prev)
    tasks = out["content"]["tasks"]
    ship = [t for t in tasks if t["title"] == "Ship docs"][0]
    assert ship["status"] == "in_progress"
    assert ship["owner"] == "Sam"


def test_task_state_paraphrase_carry_forward_match():
    source = {
        "artifact_id": "art_plan_new",
        "artifact_type": "plan",
        "content": {"steps": ["Release documentation", "Run tests"]},
    }
    prev = {
        "artifact_id": "art_ts_prev",
        "artifact_type": "task_state",
        "thread_id": "thr_docs",
        "content": {
            "thread_id": "thr_docs",
            "tasks": [
                {"task_id": "tid_docs", "title": "Ship docs", "status": "in_progress", "owner": "Alex", "source_artifact_id": "art_old"}
            ],
            "rollups": {"open_count": 0, "in_progress_count": 1, "done_count": 0, "blocked_count": 0},
            "suggested_updates": [],
        },
    }
    out = build_task_state_from_artifact(source_artifact=source, thread_id="thr_docs", previous_task_state=prev)
    task = [t for t in out["content"]["tasks"] if "documentation" in t["title"].lower()][0]
    assert task["task_id"] == "tid_docs"
    assert task["status"] == "in_progress"


def test_task_state_status_suggestions_from_hint_text():
    source = {
        "artifact_id": "art_plan_new",
        "artifact_type": "plan",
        "content": {"steps": ["Ship docs", "Run tests"]},
    }
    out = build_task_state_from_artifact(
        source_artifact=source,
        thread_id="thr_docs",
        previous_task_state=None,
        status_hint_text="ship docs done yesterday, run tests in progress",
    )
    updates = out["content"].get("suggested_updates") or []
    statuses = {u["task_id"]: u["suggested_status"] for u in updates}
    assert "done" in statuses.values()
    assert "in_progress" in statuses.values()


def test_global_index_compaction_removes_stale_rows(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    # stale row (> 180d ago)
    store.append(
        "u1",
        {
            "artifact_id": "art_old",
            "artifact_type": "plan",
            "thread_id": "thr_old",
            "status": "open",
            "tags": ["docs"],
            "timestamp": "2020-01-01T00:00:00+00:00",
            "content": {"objective": "x", "steps": ["a"]},
        },
    )
    # fresh row
    store.append(
        "u1",
        {
            "artifact_id": "art_new",
            "artifact_type": "plan",
            "thread_id": "thr_new",
            "status": "open",
            "tags": ["docs"],
            "content": {"objective": "y", "steps": ["b"]},
        },
    )
    stats = store.compact_global_indexes(max_age_days=180)
    snap = store.get_index_snapshot()
    assert stats["thread_rows"] >= 1
    assert "thr_new" in snap["by_thread_id"]
    assert "thr_old" not in snap["by_thread_id"]


def test_turn_level_simulated_interop_thread_selection_and_task_carry_forward(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    prev = {
        "artifact_id": "art_prev_ts",
        "artifact_type": "task_state",
        "thread_id": "thr_abc",
        "status": "open",
        "tags": ["docs"],
        "content": {
            "thread_id": "thr_abc",
            "tasks": [{"task_id": "tid_docs", "title": "Ship docs", "status": "in_progress", "owner": "Sam", "source_artifact_id": "art_p1"}],
            "rollups": {"open_count": 0, "in_progress_count": 1, "done_count": 0, "blocked_count": 0},
            "suggested_updates": [],
        },
    }
    store.append("u1", prev)
    store.append("u1", {"artifact_id": "art_plan_prev", "artifact_type": "plan", "thread_id": "thr_abc", "status": "open", "tags": ["docs"], "content": {"objective": "docs", "steps": ["Ship docs"]}})

    idx = store.get_index_snapshot()
    chosen = choose_thread_id_for_request("resume docs plan", {"thread_id": None, "artifact_intent": "plan", "tags": ["docs"]}, idx)
    assert chosen == "thr_abc"

    out = build_task_state_from_artifact(
        source_artifact={"artifact_id": "art_plan_new", "artifact_type": "plan", "thread_id": chosen, "content": {"steps": ["Release documentation"]}},
        thread_id=chosen,
        previous_task_state=store.get_last("u1", "task_state"),
        status_hint_text="release documentation done",
    )
    docs_task = [t for t in out["content"]["tasks"] if "documentation" in t["title"].lower()][0]
    assert docs_task["task_id"] == "tid_docs"
    assert any(u.get("suggested_status") == "done" for u in out["content"].get("suggested_updates") or [])


def test_status_inference_clause_scoping_avoids_cross_task_pollution():
    source = {
        "artifact_id": "art_plan_scope",
        "artifact_type": "plan",
        "content": {"steps": ["Ship docs", "Run tests"]},
    }
    out = build_task_state_from_artifact(
        source_artifact=source,
        thread_id="thr_scope",
        status_hint_text="ship docs done, run tests in progress",
    )
    updates = out["content"].get("suggested_updates") or []
    assert any(u.get("suggested_status") == "done" for u in updates)
    assert any(u.get("suggested_status") == "in_progress" for u in updates)


def test_adaptive_compaction_keeps_open_longer_than_non_adaptive(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append(
        "u1",
        {
            "artifact_id": "art_open_old",
            "artifact_type": "plan",
            "thread_id": "thr_open_old",
            "status": "open",
            "tags": ["docs"],
            "timestamp": "2025-04-01T00:00:00+00:00",
            "content": {"objective": "x", "steps": ["a"]},
        },
    )
    # adaptive keeps open rows longer (>=365d window)
    store.compact_global_indexes(max_age_days=180, adaptive=True)
    snap_a = store.get_index_snapshot()
    keep_adaptive = "thr_open_old" in snap_a["by_thread_id"]

    # non-adaptive uses strict max_age_days
    store.compact_global_indexes(max_age_days=180, adaptive=False)
    snap_b = store.get_index_snapshot()
    keep_non_adaptive = "thr_open_old" in snap_b["by_thread_id"]

    assert keep_adaptive is True
    assert keep_non_adaptive is False
