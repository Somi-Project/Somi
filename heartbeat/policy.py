from __future__ import annotations

from datetime import datetime


class HeartbeatPolicy:
    def __init__(self, breadcrumb_minutes: int, dedupe_cooldown_seconds: int):
        self.breadcrumb_minutes = breadcrumb_minutes
        self.dedupe_cooldown_seconds = dedupe_cooldown_seconds
        self.last_breadcrumb_ts: datetime | None = None
        self._sig_last_ts: dict[str, datetime] = {}
        self._last_status_level = "INFO"
        self._last_paused = False

    def should_emit_ui_event(self, event: dict, now: datetime) -> bool:
        etype = event.get("type")
        level = event.get("level", "INFO")

        if etype == "tick":
            return False

        if etype == "lifecycle":
            return True

        if level in {"WARN", "ERROR"}:
            return True

        if etype == "status":
            paused = bool(event.get("meta", {}).get("paused", False))
            transitioned = (level != self._last_status_level) or (paused != self._last_paused)
            self._last_status_level = level
            self._last_paused = paused
            return transitioned

        return False

    def should_update_label(self, event: dict) -> bool:
        return event.get("type") in {"status", "lifecycle", "alert", "error"}

    def allow_breadcrumb(self, now: datetime) -> bool:
        if self.last_breadcrumb_ts is None:
            self.last_breadcrumb_ts = now
            return True
        elapsed_minutes = (now - self.last_breadcrumb_ts).total_seconds() / 60.0
        if elapsed_minutes >= self.breadcrumb_minutes:
            self.last_breadcrumb_ts = now
            return True
        return False

    def dedupe_ok(self, event_sig: str, now: datetime) -> bool:
        last = self._sig_last_ts.get(event_sig)
        if last is None:
            self._sig_last_ts[event_sig] = now
            return True
        elapsed = (now - last).total_seconds()
        if elapsed >= self.dedupe_cooldown_seconds:
            self._sig_last_ts[event_sig] = now
            return True
        return False
