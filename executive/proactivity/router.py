from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings


def _safe_zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(timezone or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


@dataclass
class InterruptBudget:
    amount: int | None = None
    spent_by_day: dict[str, int] = field(default_factory=dict)
    notify_count_by_day: dict[str, int] = field(default_factory=dict)
    message_count_by_day: dict[str, int] = field(default_factory=dict)
    brief_candidate_count_by_day: dict[str, int] = field(default_factory=dict)
    brief_candidate_keys_by_day: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount is None:
            self.amount = int(getattr(settings, "PROACTIVITY_DAILY_INTERRUPT_BUDGET", 100))

    def _day_key(self, now: datetime, timezone: str) -> str:
        local = now.astimezone(_safe_zone(timezone)) if now.tzinfo else now.replace(tzinfo=_safe_zone(timezone))
        return local.date().isoformat()

    def can_spend(self, now: datetime, timezone: str, ssi: int, max_notifications: int) -> bool:
        key = self._day_key(now, timezone)
        spent = self.spent_by_day.get(key, 0)
        sent = self.notify_count_by_day.get(key, 0)
        return spent + max(10, round(ssi / 2)) <= self.amount and sent < max_notifications

    def spend(self, now: datetime, timezone: str, ssi: int) -> None:
        key = self._day_key(now, timezone)
        self.spent_by_day[key] = self.spent_by_day.get(key, 0) + max(10, round(ssi / 2))
        self.notify_count_by_day[key] = self.notify_count_by_day.get(key, 0) + 1
        self.message_count_by_day[key] = self.message_count_by_day.get(key, 0) + 1

    def can_queue_brief_candidate(self, now: datetime, timezone: str, max_messages: int, candidate_key: str | None = None) -> bool:
        key = self._day_key(now, timezone)
        sent = self.message_count_by_day.get(key, 0)
        queued = self.brief_candidate_count_by_day.get(key, 0)
        if candidate_key:
            seen = self.brief_candidate_keys_by_day.get(key, set())
            if candidate_key in seen:
                return True
        # reserve capacity so queued candidates remain within daily message budget.
        return sent + queued < max_messages

    def queue_brief_candidate(self, now: datetime, timezone: str, candidate_key: str | None = None) -> bool:
        key = self._day_key(now, timezone)
        if candidate_key:
            seen = self.brief_candidate_keys_by_day.setdefault(key, set())
            if candidate_key in seen:
                return False
            seen.add(candidate_key)
        self.brief_candidate_count_by_day[key] = self.brief_candidate_count_by_day.get(key, 0) + 1
        return True

    def pending_brief_candidates(self, now: datetime, timezone: str) -> int:
        return self.brief_candidate_count_by_day.get(self._day_key(now, timezone), 0)

    def mark_brief_delivered(self, now: datetime, timezone: str, consumed_candidates: int = 1) -> None:
        key = self._day_key(now, timezone)
        current = self.brief_candidate_count_by_day.get(key, 0)
        consumed = max(1, int(consumed_candidates))
        self.brief_candidate_count_by_day[key] = max(0, current - consumed)
        # We cannot deterministically map which candidate keys were consumed by the external dispatcher.
        # Resetting the key cache avoids stale-key suppression after partial brief delivery.
        self.brief_candidate_keys_by_day[key] = set()
        self.message_count_by_day[key] = self.message_count_by_day.get(key, 0) + 1


class SignalRouter:
    def __init__(self, budget: InterruptBudget | None = None):
        self.budget = budget or InterruptBudget()

    def _candidate_key(self, signal: dict) -> str | None:
        explicit = str(signal.get("candidate_id") or "").strip()
        if explicit:
            return explicit
        identity_parts = [
            str(signal.get("project_id") or "").strip(),
            str(signal.get("goal_id") or "").strip(),
            str(signal.get("signal_type") or "").strip(),
            str(signal.get("entity_id") or "").strip(),
        ]
        if any(identity_parts):
            return "|".join([str(signal.get("topic") or "").strip(), *identity_parts])
        # no stable identity available: do not dedupe by key to avoid collapsing distinct candidates
        return None

    def _downgrade_or_log(self, signal: dict, now: datetime, timezone: str, prefs: dict) -> str:
        effective = dict(prefs)
        if "brief_windows" not in effective:
            effective["brief_windows"] = {"morning": "08:00", "evening": "18:00"}
        if next_brief_window(now, effective, timezone) is None:
            return "log_only"
        max_messages = max(0, int(effective.get("limits", {}).get("max_messages_per_day", int(getattr(settings, "PROACTIVITY_MAX_MESSAGES_PER_DAY", 3)))))
        key = self._candidate_key(signal)
        if not self.budget.can_queue_brief_candidate(now, timezone, max_messages, candidate_key=key):
            return "log_only"
        self.budget.queue_brief_candidate(now, timezone, candidate_key=key)
        return "include_in_next_brief"

    def route(self, signal: dict, prefs: dict, now: datetime, timezone: str) -> str:
        if not bool(getattr(settings, "PROACTIVITY_ENABLED", True)):
            return "log_only"
        ssi = int(signal.get("ssi") or 0)
        topic = str(signal.get("topic") or "strategic_signals")
        mode = prefs.get("topics", {}).get(topic, "notify")
        if mode == "off":
            return "log_only"
        thresholds = dict(prefs.get("thresholds", {}))
        if ssi < int(thresholds.get("brief", 45)):
            return "log_only"
        if mode == "brief_only":
            return self._downgrade_or_log(signal, now, timezone, prefs)
        if mode == "alerts_only" and not signal.get("is_alert"):
            return self._downgrade_or_log(signal, now, timezone, prefs)
        if ssi < int(thresholds.get("notify", 72)):
            return self._downgrade_or_log(signal, now, timezone, prefs)
        if signal.get("quiet_hours") and not signal.get("critical"):
            return self._downgrade_or_log(signal, now, timezone, prefs)
        if signal.get("in_meeting") and not signal.get("critical"):
            return self._downgrade_or_log(signal, now, timezone, prefs)
        if signal.get("active_recently") and not signal.get("critical"):
            return self._downgrade_or_log(signal, now, timezone, prefs)

        max_n = max(0, int(prefs.get("limits", {}).get("max_notifications_per_day", int(getattr(settings, "PROACTIVITY_MAX_NOTIFICATIONS_PER_DAY", 1)))))
        if not self.budget.can_spend(now, timezone, ssi, max_n):
            return self._downgrade_or_log(signal, now, timezone, prefs)
        self.budget.spend(now, timezone, ssi)
        return "notify_now"

    def mark_brief_delivered(self, now: datetime, timezone: str, consumed_candidates: int = 1) -> None:
        self.budget.mark_brief_delivered(now, timezone, consumed_candidates=consumed_candidates)


def next_brief_window(now: datetime, prefs: dict, timezone: str):
    tz = _safe_zone(timezone)
    local = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    candidates = []
    for key in ("morning", "evening"):
        t = prefs.get("brief_windows", {}).get(key)
        if not t:
            continue
        try:
            hh, mm = [int(x) for x in str(t).split(":", 1)]
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                continue
        except Exception:
            continue
        dt = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt < local:
            dt = dt + timedelta(days=1)
        candidates.append(dt)
    return min(candidates) if candidates else None
