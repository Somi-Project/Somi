from __future__ import annotations

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


class GoalNudgeTask:
    name = "goal_nudge"
    min_interval_seconds = 14400
    enabled_flag_name = "HB_FEATURE_GOAL_NUDGES"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        return bool(ctx.settings.get("HB_FEATURE_GOAL_NUDGES", True))

    def run(self, ctx: HeartbeatContext) -> list[dict]:
        provider = ctx.settings.get("HB_GOAL_NUDGE_PROVIDER")
        if not callable(provider):
            return []
        try:
            goals = provider() or []
        except Exception:
            return []
        if not goals:
            return []

        top = goals[0]
        title = str(top.get("title", "your goal")).strip() or "your goal"
        progress = int(float(top.get("progress", 0.0) or 0.0) * 100)
        ev = make_event(
            "INFO",
            "nudge",
            f"Goal nudge: {title}",
            detail=f"Small step check-in (progress {progress}%).",
            meta={"kind": "goal_nudge", "goal": title},
            timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
        )
        return [ev]
