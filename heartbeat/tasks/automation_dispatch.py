from __future__ import annotations

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


class AutomationDispatchTask:
    name = "automation_dispatch"
    min_interval_seconds = 60
    enabled_flag_name = "HB_FEATURE_AUTOMATION_DISPATCH"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        return bool(ctx.settings.get("HB_FEATURE_AUTOMATION_DISPATCH", True))

    def run(self, ctx: HeartbeatContext) -> list[dict]:
        provider = ctx.settings.get("HB_AUTOMATION_PROVIDER")
        if not callable(provider):
            return []
        try:
            results = list(provider() or [])
        except Exception:
            return []
        events = []
        for result in results[:3]:
            automation = dict((result or {}).get("automation") or {})
            receipt = dict((result or {}).get("receipt") or {})
            title = str(automation.get("name") or "Automation").strip() or "Automation"
            status = str(receipt.get("status") or "queued")
            channel = str(receipt.get("channel") or automation.get("target_channel") or "desktop")
            events.append(
                make_event(
                    "INFO",
                    "automation",
                    f"Automation run: {title}",
                    detail=f"{status} via {channel}",
                    meta={"automation_id": automation.get("automation_id"), "channel": channel, "status": status},
                    timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
                )
            )
        return events
