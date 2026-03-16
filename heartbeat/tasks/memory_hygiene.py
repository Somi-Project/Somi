from __future__ import annotations

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


class MemoryHygieneTask:
    name = "memory_hygiene"
    min_interval_seconds = 900
    enabled_flag_name = "HB_FEATURE_MEMORY_HYGIENE"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        return bool(ctx.settings.get("HB_FEATURE_MEMORY_HYGIENE", True))

    def run(self, ctx: HeartbeatContext) -> list[dict]:
        provider = ctx.settings.get("HB_MEMORY_HYGIENE_PROVIDER")
        if not callable(provider):
            return []
        try:
            report = dict(provider() or {})
        except Exception:
            return []

        expired_count = int(report.get("expired_count") or 0)
        issue_count = int(report.get("scan_issue_count") or 0)
        snapshot_refreshed = bool(report.get("snapshot_present") or report.get("snapshot_refreshed"))

        if expired_count <= 0 and issue_count <= 0 and not snapshot_refreshed:
            return []

        level = "WARN" if issue_count > 0 else "INFO"
        detail = (
            f"Expired={expired_count}, scan_issues={issue_count}, "
            f"snapshot={'yes' if snapshot_refreshed else 'no'}"
        )
        return [
            make_event(
                level,
                "maintenance",
                "Memory hygiene check",
                detail=detail,
                meta=report,
                timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
            )
        ]
