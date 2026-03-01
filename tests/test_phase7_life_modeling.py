from __future__ import annotations

from datetime import datetime, timedelta, timezone

from executive.life_modeling.goal_models import derive_goal_candidates
from executive.life_modeling.heartbeat_v2 import build_heartbeat_v2
from executive.life_modeling.patterns import BANNED_WORDS, detect_patterns
from executive.life_modeling.project_clustering import cluster_projects


def _now_minus(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _items(n: int = 6) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append(
            {
                "id": f"t{i}",
                "type": "task",
                "title": f"Task {i}",
                "tags": ["ops", f"batch{i%3}"],
                "status": "open" if i % 2 == 0 else "in_progress",
                "created_at": _now_minus(4),
                "updated_at": _now_minus(i % 5),
                "due_at": _now_minus(1 if i % 2 == 0 else -1),
                "thread_ref": f"thr{i%2}",
            }
        )
    return rows


def test_project_id_stability(tmp_path):
    items = _items(5)
    sp = tmp_path / "cluster_state.json"
    clusters1, _ = cluster_projects(items, state_path=str(sp))
    clusters2, _ = cluster_projects(items, state_path=str(sp), prev_clusters=clusters1)
    ids1 = [c["project_id"] for c in clusters1]
    ids2 = [c["project_id"] for c in clusters2]
    assert ids1 == ids2


def test_cap_enforcement():
    items = []
    for i in range(100):
        items.append({"id": f"x{i}", "type": "task", "title": f"X{i}", "tags": [f"p{i}"] if i else ["p0"], "status": "open", "updated_at": _now_minus(1), "thread_ref": None})
    clusters, _ = cluster_projects(items, max_active_projects=20, min_items_per_project=1)
    assert len(clusters) <= 20


def test_evidence_required_for_links(tmp_path):
    clusters, _ = cluster_projects(_items(6), state_path=str(tmp_path / "state.json"))
    assert clusters
    for c in clusters:
        for iid in c.get("linked_item_ids") or []:
            assert iid in (c.get("evidence") or {})
            assert (c.get("evidence") or {}).get(iid, {}).get("artifact_ids")


def test_goal_creation_guardrail():
    projects = [{"project_id": "p1", "tags": ["delivery"], "open_items": 10}]
    candidates = derive_goal_candidates(projects)
    assert all(c.get("requires_confirmation") is True for c in candidates)
    # no confirmed goals are auto-created in phase 7 helper
    assert isinstance(candidates, list)


def test_heartbeat_generated_with_enrichment_off():
    items = _items(4)
    projects, _ = cluster_projects(items, min_items_per_project=1)
    goals = [{"goal_id": "g1", "linked_project_ids": [projects[0]["project_id"]]}] if projects else []
    hb = build_heartbeat_v2(items, projects, goals, patterns=[], calendar_snapshot={"conflicts": []})
    assert hb["artifact_type"] == "heartbeat_v2"
    assert isinstance(hb.get("summary"), str)
    assert hb.get("evidence_artifact_ids")


def test_cluster_thrash_guard_same_inputs_twice(tmp_path):
    items = _items(7)
    sp = tmp_path / "st.json"
    c1, s1 = cluster_projects(items, state_path=str(sp))
    c2, s2 = cluster_projects(items, state_path=str(sp), prev_clusters=c1)
    a1 = s1.get("item_assignments")
    a2 = s2.get("item_assignments")
    assert {k: v.get("project_id") for k, v in a1.items()} == {k: v.get("project_id") for k, v in a2.items()}


def test_banned_word_check_for_pattern_descriptions():
    items = _items(10)
    for i in range(3):
        items[i]["status"] = "reopened"
    patterns = detect_patterns(items, projects=[{"project_id": "p1", "open_items": 3}, {"project_id": "p2", "open_items": 2}, {"project_id": "p3", "open_items": 2}])
    assert patterns
    for p in patterns:
        desc = str(p.get("description") or "").lower()
        assert not any(b in desc for b in BANNED_WORDS)
