from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from executive.life_modeling import list_goal_link_proposals, list_pending_goal_link_proposals
from executive.life_modeling.calendar_snapshot import (
    GOOGLE_CALENDAR_READONLY_SCOPE,
    MSGRAPH_CALENDAR_READ_SCOPE,
    GoogleCalendarProvider,
    MsGraphCalendarProvider,
    get_calendar_provider,
)
from executive.life_modeling.confirmation_queue import GoalLinkConfirmationQueue
from handlers.contracts.store import ArtifactStore


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_calendar_provider_factory_modes():
    s1 = SimpleNamespace(PHASE7_CALENDAR_PROVIDER="google", PHASE7_GOOGLE_CALENDAR_ACCESS_TOKEN="", PHASE7_GOOGLE_CALENDAR_ID="primary")
    s2 = SimpleNamespace(PHASE7_CALENDAR_PROVIDER="msgraph", PHASE7_MSGRAPH_ACCESS_TOKEN="")
    p1 = get_calendar_provider(s1)
    p2 = get_calendar_provider(s2)
    assert isinstance(p1, GoogleCalendarProvider)
    assert isinstance(p2, MsGraphCalendarProvider)
    assert GOOGLE_CALENDAR_READONLY_SCOPE.endswith("readonly")
    assert MSGRAPH_CALENDAR_READ_SCOPE == "Calendars.Read"


def test_remote_calendar_providers_fail_closed_without_token():
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=1)
    assert GoogleCalendarProvider(access_token="").get_events(start, end) == []
    assert MsGraphCalendarProvider(access_token="").get_events(start, end) == []


def test_confirmation_queue_enqueue_and_list(tmp_path):
    q = GoalLinkConfirmationQueue(path=str(tmp_path / "queue.json"))
    added = q.enqueue([
        {"proposal_id": "glp_1", "goal_id": "goal_1", "project_id": "proj_1", "requires_confirmation": True},
        {"proposal_id": "glp_1", "goal_id": "goal_1", "project_id": "proj_1", "requires_confirmation": True},
    ])
    assert added == 1
    pending = q.list_pending()
    assert len(pending) == 1
    assert pending[0]["proposal_id"] == "glp_1"


def test_artifact_store_sharding_by_date(tmp_path, monkeypatch):
    from handlers.contracts import store as store_mod

    monkeypatch.setattr(store_mod, "runtime_settings", SimpleNamespace(
        ARTIFACT_STORE_SHARD_BY_DATE=True,
        ARTIFACT_STORE_SHARD_DIRNAME="shards",
        ARTIFACT_STORE_MIRROR_PRIMARY_WHEN_SHARDED=False,
    ))

    st = ArtifactStore(root_dir=str(tmp_path / "artifacts"))
    artifact = {
        "artifact_id": "a1",
        "artifact_type": "task_state",
        "contract_name": "task_state",
        "timestamp": _iso(0),
        "content": {"tasks": [{"task_id": "t1", "title": "x", "status": "open"}]},
    }
    st.append("user1", artifact)
    shard_dir = tmp_path / "artifacts" / "shards"
    files = list(shard_dir.glob("user1.*.jsonl"))
    assert files


def test_list_pending_goal_link_proposals_callable():
    rows = list_pending_goal_link_proposals()
    assert isinstance(rows, list)


def test_confirmation_queue_get_and_resolve(tmp_path):
    q = GoalLinkConfirmationQueue(path=str(tmp_path / "queue.json"))
    q.enqueue([{"proposal_id": "glp_2", "goal_id": "goal_2", "project_id": "proj_2", "requires_confirmation": True}])
    row = q.get("glp_2")
    assert row is not None
    assert row["status"] == "pending"
    assert q.resolve("glp_2", approved=False) is True
    row2 = q.get("glp_2")
    assert row2 is not None and row2["status"] == "rejected"


def test_artifact_store_sharding_mirror_primary(tmp_path, monkeypatch):
    from handlers.contracts import store as store_mod

    monkeypatch.setattr(store_mod, "runtime_settings", SimpleNamespace(
        ARTIFACT_STORE_SHARD_BY_DATE=True,
        ARTIFACT_STORE_SHARD_DIRNAME="shards",
        ARTIFACT_STORE_MIRROR_PRIMARY_WHEN_SHARDED=True,
    ))

    st = ArtifactStore(root_dir=str(tmp_path / "artifacts"))
    artifact = {
        "artifact_id": "a2",
        "artifact_type": "task_state",
        "contract_name": "task_state",
        "timestamp": _iso(0),
        "content": {"tasks": [{"task_id": "t2", "title": "y", "status": "open"}]},
    }
    st.append("user2", artifact)
    primary = tmp_path / "artifacts" / "user2.jsonl"
    shard_dir = tmp_path / "artifacts" / "shards"
    shard_files = list(shard_dir.glob("user2.*.jsonl"))
    assert primary.exists()
    assert shard_files


def test_queue_telemetry_records_depth_and_latency(tmp_path, monkeypatch):
    import executive.life_modeling.confirmation_queue as cq

    monkeypatch.setattr(cq.settings, "PHASE7_TELEMETRY_PATH", str(tmp_path / "telemetry.json"), raising=False)
    q = cq.GoalLinkConfirmationQueue(path=str(tmp_path / "queue.json"))
    q.enqueue([{"proposal_id": "glp_tele", "goal_id": "goal_1", "project_id": "proj_1"}])
    assert q.resolve("glp_tele", approved=True) is True

    tele = json.loads((tmp_path / "telemetry.json").read_text(encoding="utf-8"))
    assert int((tele.get("queue") or {}).get("max_depth_seen") or 0) >= 1
    assert int((tele.get("queue") or {}).get("approved_count") or 0) >= 1


def test_shard_telemetry_records_file_growth(tmp_path, monkeypatch):
    from handlers.contracts import store as store_mod

    monkeypatch.setattr(store_mod, "runtime_settings", SimpleNamespace(
        ARTIFACT_STORE_SHARD_BY_DATE=True,
        ARTIFACT_STORE_SHARD_DIRNAME="shards",
        ARTIFACT_STORE_MIRROR_PRIMARY_WHEN_SHARDED=False,
        PHASE7_TELEMETRY_PATH=str(tmp_path / "telemetry.json"),
    ))

    st = store_mod.ArtifactStore(root_dir=str(tmp_path / "artifacts"))
    artifact = {
        "artifact_id": "a_tele",
        "artifact_type": "task_state",
        "contract_name": "task_state",
        "timestamp": _iso(0),
        "content": {"tasks": [{"task_id": "t_tele", "title": "tele", "status": "open"}]},
    }
    st.append("user_tele", artifact)
    tele = json.loads((tmp_path / "telemetry.json").read_text(encoding="utf-8"))
    assert int((tele.get("shards") or {}).get("current_files") or 0) >= 1




def test_confirmation_queue_list_by_status(tmp_path):
    q = GoalLinkConfirmationQueue(path=str(tmp_path / "queue_status.json"))
    q.enqueue([{"proposal_id": "glp_s1", "goal_id": "g1", "project_id": "p1"}])
    assert q.resolve("glp_s1", approved=True) is True
    all_rows = q.list_by_status("all")
    approved = q.list_by_status("approved")
    pending = q.list_by_status("pending")
    assert len(all_rows) >= 1
    assert len(approved) >= 1
    assert len(pending) == 0


def test_life_modeling_list_goal_link_proposals_api():
    rows = list_goal_link_proposals("all")
    assert isinstance(rows, list)


def test_gui_helper_date_parser_and_proposal_validator():
    pytest.importorskip("PyQt6")
    from gui.executivegui import _looks_like_proposal_id, _parse_date

    assert _looks_like_proposal_id("glp_abc123") is True
    assert _looks_like_proposal_id("bad") is False
    assert _parse_date("2026-01-01") is not None
    assert _parse_date("bad-date") is None
