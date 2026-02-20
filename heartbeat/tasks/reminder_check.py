from __future__ import annotations

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


class ReminderCheckTask:
    name = "reminder_check"
    min_interval_seconds = 60
    enabled_flag_name = "HB_FEATURE_REMINDERS"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        return bool(ctx.settings.get("HB_FEATURE_REMINDERS", True))

    def run(self, ctx: HeartbeatContext) -> list[dict]:
        provider = ctx.settings.get("HB_REMINDER_PROVIDER")
        if not callable(provider):
            return []
        try:
            due = provider() or []
        except Exception:
            return []
        events = []
        for r in due[:3]:
            title = str(r.get("title", "Reminder")).strip() or "Reminder"
            due_ts = str(r.get("due_ts", "soon"))
            events.append(
                make_event(
                    "INFO",
                    "alert",
                    f"Reminder: {title}",
                    detail=f"Due {due_ts}",
                    meta={"kind": "reminder", "reminder_id": r.get("reminder_id")},
                    timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
                )
            )
        return events
