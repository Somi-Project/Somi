from __future__ import annotations

from datetime import datetime, timedelta, timezone

from executive.life_modeling.artifact_store import ArtifactStore
from executive.proactivity.alerts import AlertRecord, AlertsLane
from executive.proactivity.briefs import BriefGenerator
from executive.proactivity.feedback_intent import parse_feedback_intent
from executive.proactivity.preferences import compile_effective_preferences
from executive.proactivity.router import InterruptBudget, SignalRouter
from executive.proactivity.signal_engine import ProactivitySignalEngine, has_progress_event
from executive.proactivity.ssi import compute_ssi


def test_ssi_deterministic_stability():
    s1 = compute_ssi(0.9, 0.8, 0.7, 1.0, 0.9)
    s2 = compute_ssi(0.9, 0.8, 0.7, 1.0, 0.9)
    assert s1 == s2


def test_two_threshold_gating_notify_brief_log():
    prefs = {"topics": {"weather": "notify"}, "thresholds": {"notify": 70, "brief": 40}, "limits": {"max_notifications_per_day": 2}}
    router = SignalRouter(InterruptBudget(100))
    now = datetime.now(timezone.utc)
    assert router.route({"topic": "weather", "ssi": 80}, prefs, now, "UTC") == "notify_now"
    assert router.route({"topic": "weather", "ssi": 55}, prefs, now, "UTC") == "include_in_next_brief"
    assert router.route({"topic": "weather", "ssi": 20}, prefs, now, "UTC") == "log_only"


def test_interrupt_budget_downgrades():
    prefs = {"topics": {"weather": "notify"}, "thresholds": {"notify": 70, "brief": 40}, "limits": {"max_notifications_per_day": 5}}
    router = SignalRouter(InterruptBudget(50))
    out1 = router.route({"topic": "weather", "ssi": 80}, prefs, datetime.now(timezone.utc), "UTC")
    out2 = router.route({"topic": "weather", "ssi": 80}, prefs, datetime.now(timezone.utc), "UTC")
    assert out1 == "notify_now"
    assert out2 == "include_in_next_brief"


def test_timing_deferral_active_meeting_quiet_hours():
    prefs = {"topics": {"weather": "notify"}, "thresholds": {"notify": 70, "brief": 40}, "limits": {"max_notifications_per_day": 2}}
    router = SignalRouter(InterruptBudget(100))
    base = {"topic": "weather", "ssi": 90, "critical": False}
    assert router.route({**base, "active_recently": True}, prefs, datetime.now(timezone.utc), "UTC") == "include_in_next_brief"
    assert router.route({**base, "in_meeting": True}, prefs, datetime.now(timezone.utc), "UTC") == "include_in_next_brief"
    assert router.route({**base, "quiet_hours": True}, prefs, datetime.now(timezone.utc), "UTC") == "include_in_next_brief"




def test_global_proactivity_toggle_forces_log_only(monkeypatch):
    from executive.proactivity import router as router_mod

    monkeypatch.setattr(router_mod.settings, "PROACTIVITY_ENABLED", False)
    prefs = {"topics": {"weather": "notify"}, "thresholds": {"notify": 70, "brief": 40}, "limits": {"max_notifications_per_day": 2}}
    router = SignalRouter(InterruptBudget(100))
    assert router.route({"topic": "weather", "ssi": 95}, prefs, datetime.now(timezone.utc), "UTC") == "log_only"

def test_router_logs_when_all_windows_disabled():
    prefs = {
        "topics": {"weather": "brief_only"},
        "thresholds": {"notify": 70, "brief": 40},
        "limits": {"max_notifications_per_day": 2},
        "brief_windows": {"morning": None, "evening": None},
    }
    router = SignalRouter(InterruptBudget(100))
    assert router.route({"topic": "weather", "ssi": 65}, prefs, datetime.now(timezone.utc), "UTC") == "log_only"




def test_router_handles_missing_thresholds_dict():
    prefs = {"topics": {"weather": "notify"}, "limits": {"max_notifications_per_day": 2}}
    router = SignalRouter(InterruptBudget(100))
    out = router.route({"topic": "weather", "ssi": 50}, prefs, datetime.now(timezone.utc), "UTC")
    assert out == "include_in_next_brief"


def test_interrupt_budget_default_uses_settings(monkeypatch):
    from executive.proactivity import router as router_mod

    monkeypatch.setattr(router_mod.settings, "PROACTIVITY_DAILY_INTERRUPT_BUDGET", 37)
    b = router_mod.InterruptBudget()
    assert b.amount == 37









def test_partial_brief_delivery_clears_stale_candidate_keys():
    prefs = {
        "topics": {"weather": "brief_only"},
        "thresholds": {"notify": 70, "brief": 40},
        "limits": {"max_notifications_per_day": 1, "max_messages_per_day": 3},
        "brief_windows": {"morning": "08:00", "evening": "18:00"},
    }
    now = datetime.now(timezone.utc)
    router = SignalRouter(InterruptBudget(100))

    sig_a = {"topic": "weather", "ssi": 60, "entity_id": "a"}
    sig_b = {"topic": "weather", "ssi": 60, "entity_id": "b"}
    assert router.route(sig_a, prefs, now, "UTC") == "include_in_next_brief"
    assert router.route(sig_b, prefs, now, "UTC") == "include_in_next_brief"

    # consume only one candidate; key cache should be reset to avoid stale suppression.
    router.mark_brief_delivered(now, "UTC", consumed_candidates=1)

    # re-seeing 'a' should be allowed to reserve again after delivery event.
    assert router.route(sig_a, prefs, now, "UTC") == "include_in_next_brief"

def test_brief_candidate_without_identity_does_not_dedupe():
    prefs = {
        "topics": {"weather": "brief_only"},
        "thresholds": {"notify": 70, "brief": 40},
        "limits": {"max_notifications_per_day": 1, "max_messages_per_day": 2},
        "brief_windows": {"morning": "08:00", "evening": "18:00"},
    }
    now = datetime.now(timezone.utc)
    router = SignalRouter(InterruptBudget(100))

    sig = {"topic": "weather", "ssi": 60}
    assert router.route(sig, prefs, now, "UTC") == "include_in_next_brief"
    assert router.route(sig, prefs, now, "UTC") == "include_in_next_brief"
    assert router.budget.pending_brief_candidates(now, "UTC") == 2

def test_brief_candidate_dedup_does_not_consume_extra_capacity():
    prefs = {
        "topics": {"weather": "brief_only"},
        "thresholds": {"notify": 70, "brief": 40},
        "limits": {"max_notifications_per_day": 1, "max_messages_per_day": 1},
        "brief_windows": {"morning": "08:00", "evening": "18:00"},
    }
    now = datetime.now(timezone.utc)
    router = SignalRouter(InterruptBudget(100))

    sig = {"topic": "weather", "ssi": 60, "entity_id": "same"}
    assert router.route(sig, prefs, now, "UTC") == "include_in_next_brief"
    assert router.budget.pending_brief_candidates(now, "UTC") == 1
    # duplicate signal may still route to brief but should not reserve another slot
    assert router.route(sig, prefs, now, "UTC") == "include_in_next_brief"
    assert router.budget.pending_brief_candidates(now, "UTC") == 1



def test_router_invalid_timezone_falls_back_to_utc():
    prefs = {"topics": {"weather": "notify"}, "thresholds": {"notify": 70, "brief": 40}, "limits": {"max_notifications_per_day": 2}}
    router = SignalRouter(InterruptBudget(100))
    out = router.route({"topic": "weather", "ssi": 55}, prefs, datetime.now(timezone.utc), "Not/AZone")
    assert out in {"include_in_next_brief", "log_only", "notify_now"}


def test_next_brief_window_invalid_timezone_falls_back_to_utc():
    from executive.proactivity.router import next_brief_window

    now = datetime.now(timezone.utc)
    prefs = {"brief_windows": {"morning": "08:00", "evening": "18:00"}}
    assert next_brief_window(now, prefs, "Not/AZone") is not None

def test_next_brief_window_ignores_invalid_times():
    from executive.proactivity.router import next_brief_window

    now = datetime.now(timezone.utc)
    prefs = {"brief_windows": {"morning": "bad", "evening": "25:70"}}
    assert next_brief_window(now, prefs, "UTC") is None



def test_brief_candidate_accounting_and_delivery_consumption():
    prefs = {
        "topics": {"weather": "brief_only"},
        "thresholds": {"notify": 70, "brief": 40},
        "limits": {"max_notifications_per_day": 1, "max_messages_per_day": 2},
        "brief_windows": {"morning": "08:00", "evening": "18:00"},
    }
    now = datetime.now(timezone.utc)
    router = SignalRouter(InterruptBudget(100))

    assert router.route({"topic": "weather", "ssi": 60, "entity_id": "a"}, prefs, now, "UTC") == "include_in_next_brief"
    assert router.budget.pending_brief_candidates(now, "UTC") == 1
    assert router.route({"topic": "weather", "ssi": 60, "entity_id": "b"}, prefs, now, "UTC") == "include_in_next_brief"
    assert router.budget.pending_brief_candidates(now, "UTC") == 2

    # third distinct candidate exceeds daily message capacity reservation and gets logged
    assert router.route({"topic": "weather", "ssi": 60, "entity_id": "c"}, prefs, now, "UTC") == "log_only"

    # canonical dispatcher consumes queued candidates on brief delivery
    router.mark_brief_delivered(now, "UTC", consumed_candidates=2)
    assert router.budget.pending_brief_candidates(now, "UTC") == 0

def test_grouping_single_notify_per_entity():
    engine = ProactivitySignalEngine()
    grouped = engine.group([
        {"project_id": "p1", "signal_type": "stagnation"},
        {"project_id": "p1", "signal_type": "risk"},
        {"project_id": "p1", "signal_type": "other"},
    ])
    assert len(grouped) == 1
    assert len(grouped[0]) == 2


def test_escalation_resets_on_progress_or_dismiss():
    engine = ProactivitySignalEngine()
    assert engine.update_escalation("stagnation", "x", persistent_days=2, progressed=False, dismissed=False) == 1
    assert engine.update_escalation("stagnation", "x", persistent_days=3, progressed=False, dismissed=False) == 2
    assert engine.update_escalation("stagnation", "x", persistent_days=3, progressed=True, dismissed=False) == 0


def test_stagnation_requires_progress_event_absence():
    engine = ProactivitySignalEngine()
    assert engine.stagnation("high", open_tasks=3, days_without_progress=2) is True
    assert engine.stagnation("low", open_tasks=3, days_without_progress=10) is False
    assert has_progress_event([{"type": "risk_score_decreased"}]) is True


def test_quality_filter_drops_low_value_cards(tmp_path):
    store = ArtifactStore(root_dir=str(tmp_path))
    gen = BriefGenerator(store)
    out = gen.generate(
        datetime.now(timezone.utc),
        "UTC",
        cards=[
            {"claim": "It will rain", "why_it_matters": "Commute delay", "action": "Carry umbrella"},
            {"claim": "vague"},
        ],
        alerts=[],
    )
    assert len(out["cards"]) == 1


def test_preference_precedence_and_ttl():
    now = datetime(2025, 12, 31, 12, 0, tzinfo=timezone.utc)
    updates = [
        {"timestamp": "2025-12-25T10:00:00Z", "topic": "weather", "mode": "enable", "duration": "forever"},
        {"timestamp": "2025-12-31T10:00:00Z", "topic": "weather", "mode": "disable", "duration": "today"},
    ]
    prefs = compile_effective_preferences(now, "UTC", updates)
    assert prefs["topics"]["weather"] == "off"


def test_forget_weather_today_vs_enable_forever():
    now = datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc)
    updates = [
        {"timestamp": "2026-01-01T10:00:00Z", "topic": "weather", "mode": "disable", "duration": "today"},
        {"timestamp": "2026-01-01T11:00:00Z", "topic": "weather", "mode": "enable", "duration": "forever"},
    ]
    prefs = compile_effective_preferences(now, "UTC", updates)
    assert prefs["topics"]["weather"] == "notify"


def test_snooze_blocks_temporarily_then_restores():
    updates = [
        {"timestamp": "2026-01-01T11:00:00Z", "topic": "weather", "mode": "enable", "duration": "forever"},
        {"timestamp": "2026-01-01T12:00:00Z", "topic": "weather", "mode": "snooze", "duration": "days", "ttl_days": 2},
    ]
    active = compile_effective_preferences(datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc), "UTC", updates)
    expired = compile_effective_preferences(datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc), "UTC", updates)
    assert active["topics"]["weather"] == "off"
    assert expired["topics"]["weather"] == "notify"


def test_brief_time_preferences_and_null_disable():
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    updates = [
        {"timestamp": "2026-01-01T07:00:00Z", "topic": "morning_brief", "mode": "update_time", "time": "09:00", "duration": "forever"},
        {"timestamp": "2026-01-01T08:00:00Z", "topic": "evening_brief", "mode": "disable", "time": None, "duration": "forever"},
    ]
    prefs = compile_effective_preferences(now, "UTC", updates)
    assert prefs["brief_windows"]["morning"] == "09:00"
    assert prefs["brief_windows"]["evening"] is None


def test_alert_fingerprint_suppression_with_ttl():
    lane = AlertsLane(suppression_minutes=30)
    t0 = datetime.now(timezone.utc)
    alert = AlertRecord(topic="weather", severity="critical", text="Storm warning")
    assert lane.should_emit(alert, now=t0) is True
    assert lane.should_emit(alert, now=t0 + timedelta(minutes=10)) is False
    assert lane.should_emit(alert, now=t0 + timedelta(minutes=31)) is True


def test_feedback_intent_parsing_examples():
    assert parse_feedback_intent("forget weather today")["duration"] == "today"
    assert parse_feedback_intent("start reminding me about weather")["mode"] == "enable"
    assert parse_feedback_intent("only alerts")["mode"] == "alerts_only"
    assert parse_feedback_intent("set morning brief to 9am")["time"] == "09:00"
    assert parse_feedback_intent("move morning brief to 9") ["mode"] == "update_time"
