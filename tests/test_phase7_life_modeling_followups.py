from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from executive.life_modeling.calendar_snapshot import JsonCalendarProvider, get_snapshot
from executive.life_modeling.enrichment import enrich_summary
from executive.life_modeling.goal_models import build_goal_link_proposals, derive_goal_candidates
from executive.life_modeling.indexer import Indexer
from executive.life_modeling.normalizers import normalize_artifact


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_normalizer_adapter_registry_and_confidence():
    raw = {
        "artifact_type": "task_state",
        "artifact_id": "a1",
        "thread_id": "thr1",
        "tags": ["Ops"],
        "content": {"tasks": [{"task_id": "t1", "title": "Ship", "status": "open"}]},
    }
    out = normalize_artifact(raw, strict=True)
    assert out is not None
    assert out["type"] == "task"
    assert float(out["normalization_confidence"]) >= 0.8
    assert out["adapter_used"] == "task_state"


def test_indexer_incremental_offset_update(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    file = art / "u.jsonl"
    file.write_text(json.dumps({"artifact_type": "task_state", "timestamp": _iso(-1)}) + "\n", encoding="utf-8")

    idx = Indexer(artifacts_dir=str(art), index_dir=str(tmp_path / "idx"))
    first = idx.build_or_update_index()
    assert first["items"][0]["count"] == 1

    with file.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"artifact_type": "task_state", "timestamp": _iso(0)}) + "\n")
    second = idx.build_or_update_index()
    assert second["items"][0]["count"] == 2


def test_calendar_json_provider_and_cache(tmp_path):
    cal = tmp_path / "events.json"
    rows = [
        {"id": "e1", "title": "A", "start": _iso(0), "end": _iso(1)},
        {"id": "e2", "title": "B", "start": _iso(0), "end": _iso(2)},
    ]
    cal.write_text(json.dumps(rows), encoding="utf-8")
    cache = tmp_path / "cache.json"

    snap = get_snapshot(datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(days=3), provider=JsonCalendarProvider(str(cal)), cache_path=str(cache))
    assert len(snap["events"]) == 2
    assert len(snap["conflicts"]) >= 1
    assert cache.exists()


def test_goal_link_proposal_requires_confirmation():
    projects = [{"project_id": "proj_1", "tags": ["goal:fitness", "ops"], "open_items": 2}]
    goals = [{"goal_id": "goal_1", "tags": ["goal:fitness"], "linked_project_ids": []}]
    proposals = build_goal_link_proposals(projects, goals)
    assert proposals
    assert proposals[0]["requires_confirmation"] is True


def test_goal_candidate_id_is_stable():
    projects = [{"project_id": "p1", "tags": ["goal:deep_work", "goal:deep_work"], "open_items": 10}]
    one = derive_goal_candidates(projects)
    two = derive_goal_candidates(projects)
    assert one == two


def test_enrichment_fact_lock_blocks_new_ids():
    facts = {"impacts": [{"task_id": "t1"}], "patterns": [], "calendar_conflicts": []}

    def bad_generator(_base: str, _facts: dict) -> str:
        return "New critical proj_deadbeef9999 needs urgent work now"

    txt, ok = enrich_summary("base", facts, mode="full", generator=bad_generator)
    assert ok is False
    assert "Heartbeat v2:" in txt


def test_runner_reads_multiple_rows_from_single_jsonl(tmp_path):
    from executive.life_modeling import LifeModelingRunner

    art = tmp_path / "artifacts"
    art.mkdir()
    file = art / "u.jsonl"
    rows = [
        {"artifact_id": "a1", "artifact_type": "task_state", "timestamp": _iso(-1), "tags": ["ops"], "content": {"tasks": [{"task_id": "t1", "title": "One", "status": "open"}]}} ,
        {"artifact_id": "a2", "artifact_type": "task_state", "timestamp": _iso(-1), "tags": ["ops"], "content": {"tasks": [{"task_id": "t2", "title": "Two", "status": "open"}]}} ,
    ]
    file.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    runner = LifeModelingRunner(artifacts_dir=str(art))
    res = runner.run()
    assert "projects" in res


def test_runner_dedupes_previous_cluster_history(tmp_path):
    from executive.life_modeling import LifeModelingRunner

    lm_root = tmp_path / "lm"
    art_root = tmp_path / "artifacts"
    art_root.mkdir()
    file = art_root / "u.jsonl"
    rows = [
        {"artifact_id": "a1", "artifact_type": "task_state", "timestamp": _iso(-1), "tags": ["ops"], "content": {"tasks": [{"task_id": "t1", "title": "One", "status": "open"}]}},
        {"artifact_id": "a2", "artifact_type": "task_state", "timestamp": _iso(-1), "tags": ["ops"], "content": {"tasks": [{"task_id": "t2", "title": "Two", "status": "open"}]}},
    ]
    file.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")

    runner = LifeModelingRunner(artifacts_dir=str(art_root))
    runner.store.root = lm_root
    runner.store.root.mkdir(parents=True, exist_ok=True)

    r1 = runner.run()
    r2 = runner.run()
    assert r2["projects"] <= r1["projects"] + 1


def test_bootstrap_relaxation_mode_switches_min_items(monkeypatch):
    from executive.life_modeling import LifeModelingRunner
    import executive.life_modeling as lm

    monkeypatch.setattr(lm.settings, "PHASE7_BOOTSTRAP_RELAXATION_ENABLED", True, raising=False)
    monkeypatch.setattr(lm.settings, "PHASE7_BOOTSTRAP_RELAXATION_ITEM_THRESHOLD", 6, raising=False)
    monkeypatch.setattr(lm.settings, "PHASE7_BOOTSTRAP_RELAXED_MIN_ITEMS_PER_PROJECT", 1, raising=False)
    monkeypatch.setattr(lm.settings, "PHASE7_MIN_ITEMS_PER_PROJECT", 2, raising=False)

    runner = LifeModelingRunner(artifacts_dir=str(Path('/tmp/nonexistent')))
    eff_small, used_small = runner._effective_min_items_per_project(3)
    eff_large, used_large = runner._effective_min_items_per_project(10)
    assert eff_small == 1 and used_small is True
    assert eff_large == 2 and used_large is False


def test_resolve_goal_link_updates_latest_goal_model(tmp_path):
    import executive.life_modeling as lm

    runner = lm.LifeModelingRunner(artifacts_dir=str(tmp_path / "artifacts"))
    runner.store.root = tmp_path / "lm"
    runner.store.root.mkdir(parents=True, exist_ok=True)
    runner.confirmation_queue.path = tmp_path / "queue.json"

    old = {"artifact_type": "goal_model", "goal_id": "goal_a", "linked_project_ids": ["proj_old"], "updated_at": "2026-01-01T00:00:00+00:00"}
    new = {"artifact_type": "goal_model", "goal_id": "goal_a", "linked_project_ids": ["proj_new"], "updated_at": "2026-01-02T00:00:00+00:00"}
    runner.store.write("goal_model", old)
    runner.store.write("goal_model", new)
    runner.confirmation_queue.enqueue([{"proposal_id": "glp_latest", "goal_id": "goal_a", "project_id": "proj_x"}])

    prev_runner = lm._runner
    lm._runner = runner
    try:
        ok = lm.resolve_goal_link_proposal("glp_latest", approved=True)
        assert ok is True
        latest = [x for x in list(runner.store.iter_all("goal_model") or []) if x.get("goal_id") == "goal_a"][-1]
        assert set(latest.get("linked_project_ids") or []) == {"proj_new", "proj_x"}
    finally:
        lm._runner = prev_runner


def test_tail_reader_uses_bounded_bytes(tmp_path, monkeypatch):
    import executive.life_modeling as lm

    art = tmp_path / "artifacts"
    art.mkdir()
    f = art / "u.jsonl"
    rows = []
    for i in range(200):
        rows.append({"artifact_id": f"a{i}", "artifact_type": "task_state", "timestamp": _iso(0), "content": {"tasks": [{"task_id": f"t{i}", "title": f"Task {i}", "status": "open"}]}})
    f.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(lm.settings, "PHASE7_JSONL_TAIL_READ_BYTES", 8192, raising=False)
    runner = lm.LifeModelingRunner(artifacts_dir=str(art))
    out = runner._read_recent_jsonl_rows(f, max_rows=10)
    assert len(out) <= 10
    assert all(isinstance(x, dict) for x in out)
