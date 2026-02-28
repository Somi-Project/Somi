from __future__ import annotations

import json
from pathlib import Path

from handlers.heartbeat import (
    HeartbeatEngine,
    get_active_persona,
    load_assistant_profile,
    load_persona_catalog,
    save_assistant_profile,
)


def test_profile_load_defaults_when_missing(tmp_path):
    p = tmp_path / "assistant_profile.json"
    prof = load_assistant_profile(str(p))
    assert prof["active_persona_key"] == "Name: Somi"
    assert prof["proactivity_level"] == 1
    assert prof["privacy_mode"] == "strict"


def test_profile_save_and_reload_sanitizes(tmp_path):
    p = tmp_path / "assistant_profile.json"
    save_assistant_profile(
        {
            "active_persona_key": "Name: Alex",
            "proactivity_level": 99,
            "focus_domains": ["Finance", "finance", "ops", "x", "y", "z", "a", "b"],
            "privacy_mode": "bad",
            "brief_first_interaction_of_day": True,
        },
        str(p),
    )
    prof = load_assistant_profile(str(p))
    assert prof["active_persona_key"] == "Name: Alex"
    assert prof["proactivity_level"] == 1
    assert prof["privacy_mode"] == "strict"
    assert len(prof["focus_domains"]) <= 7


def test_persona_resolution_uses_personalc():
    catalog = load_persona_catalog("config/personalC.json")
    key, persona = get_active_persona("Name: Alex", catalog)
    assert key == "Name: Alex"
    assert isinstance(persona, dict)
    bad_key, _ = get_active_persona("Name: Missing", catalog)
    assert bad_key in catalog


def _snapshot():
    return {
        "recent_open_threads": [
            {"artifact_id": "a1", "thread_id": "thr1", "type": "plan", "title": "Blocked Thread", "status": "blocked", "updated_at": "2026-01-03T00:00:00+00:00", "tags": ["ops"]},
            {"artifact_id": "a2", "thread_id": "thr2", "type": "plan", "title": "In Progress Thread", "status": "in_progress", "updated_at": "2026-01-02T00:00:00+00:00", "tags": ["finance"]},
            {"artifact_id": "a3", "thread_id": "thr3", "type": "plan", "title": "Open Thread", "status": "open", "updated_at": "2026-01-01T00:00:00+00:00", "tags": ["misc"]},
        ],
        "by_thread_id": {
            "thr1": [
                {
                    "type": "task_state",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "tags": ["ops"],
                    "data": {
                        "tasks": [
                            {"task_id": "t_blocked", "title": "Fix deploy", "status": "blocked", "source_artifact_id": "a1"},
                            {"task_id": "t_open", "title": "Write docs", "status": "open", "source_artifact_id": "a1"},
                        ]
                    },
                }
            ]
        },
    }


def test_deterministic_selection_and_bounded_output_sizes():
    engine = HeartbeatEngine()
    profile = {
        "active_persona_key": "Name: Somi",
        "proactivity_level": 1,
        "focus_domains": ["ops"],
        "privacy_mode": "strict",
        "brief_first_interaction_of_day": False,
        "last_brief_date": None,
        "last_heartbeat_at": None,
    }
    one = engine.choose_artifact(
        user_text="/brief",
        route="llm_only",
        idx_snapshot=_snapshot(),
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    two = engine.choose_artifact(
        user_text="/brief",
        route="llm_only",
        idx_snapshot=_snapshot(),
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    assert one["content"]["open_threads"][0]["status"] == "blocked"
    assert one["content"] == two["content"]
    assert len(one["content"]["open_threads"]) <= 7
    assert len(one["content"]["open_tasks"]) <= 10
    assert len(one["content"]["suggestions"]) <= 7


def test_first_interaction_of_day_one_shot_behavior():
    engine = HeartbeatEngine()
    profile = {
        "active_persona_key": "Name: Somi",
        "proactivity_level": 2,
        "focus_domains": [],
        "privacy_mode": "strict",
        "brief_first_interaction_of_day": True,
        "last_brief_date": None,
        "last_heartbeat_at": None,
    }
    art = engine.choose_artifact(
        user_text="hello",
        route="llm_only",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=True,
    )
    assert art is not None
    assert art["artifact_type"] == "daily_brief"

    profile["last_brief_date"] = art["content"]["date"]
    art2 = engine.choose_artifact(
        user_text="hello again",
        route="llm_only",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=True,
    )
    assert art2 is None


def test_never_emits_phase5_proposal_action_automatically():
    engine = HeartbeatEngine()
    profile = {
        "active_persona_key": "Name: Somi",
        "proactivity_level": 1,
        "focus_domains": [],
        "privacy_mode": "strict",
        "brief_first_interaction_of_day": False,
        "last_brief_date": None,
        "last_heartbeat_at": None,
    }
    art = engine.choose_artifact(
        user_text="/heartbeat",
        route="llm_only",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    assert art is not None
    assert art["artifact_type"] == "heartbeat_tick"
    assert art["content"]["type"] == "heartbeat_tick"


def test_read_only_routes_unaffected_weather_intent():
    from handlers.routing import decide_route

    rd = decide_route("weather in tokyo today")
    assert rd.route == "websearch"
    assert rd.signals.get("read_only") is True


def test_nl_trigger_does_not_hijack_websearch_route():
    engine = HeartbeatEngine()
    profile = {
        "active_persona_key": "Name: Somi",
        "proactivity_level": 1,
        "focus_domains": [],
        "privacy_mode": "strict",
        "brief_first_interaction_of_day": False,
        "last_brief_date": None,
        "last_heartbeat_at": None,
    }
    art = engine.choose_artifact(
        user_text="status of btc price",
        route="websearch",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    assert art is None


def test_profile_save_supports_filename_without_parent(tmp_path, monkeypatch):
    from handlers import heartbeat as hb

    # ensure no parent directory exists in path
    fn = tmp_path / "assistant_profile.json"
    hb.save_assistant_profile({"active_persona_key": "Name: Alex"}, str(fn))
    loaded = hb.load_assistant_profile(str(fn))
    assert loaded["active_persona_key"] == "Name: Alex"


def test_status_trigger_requires_work_context():
    engine = HeartbeatEngine()
    profile = {
        "active_persona_key": "Name: Somi",
        "proactivity_level": 1,
        "focus_domains": [],
        "privacy_mode": "strict",
        "brief_first_interaction_of_day": False,
        "last_brief_date": None,
        "last_heartbeat_at": None,
    }
    no_art = engine.choose_artifact(
        user_text="status of weather in tokyo",
        route="llm_only",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    yes_art = engine.choose_artifact(
        user_text="status of my task progress",
        route="llm_only",
        idx_snapshot={"recent_open_threads": [], "by_thread_id": {}},
        profile=profile,
        active_persona_key="Name: Somi",
        persona={"role": "virtual companion"},
        first_interaction_of_day=False,
    )
    assert no_art is None
    assert yes_art is not None and yes_art["artifact_type"] == "reminder_digest"
