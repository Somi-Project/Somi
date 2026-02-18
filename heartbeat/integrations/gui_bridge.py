from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class HeartbeatGUIBridge:
    def __init__(self, heartbeat_service):
        self.heartbeat_service = heartbeat_service

    def poll_events(self) -> list[dict]:
        return self.heartbeat_service.drain_events()

    def _state_snapshot(self) -> dict:
        return self.heartbeat_service.get_status().get("state", {})

    def _tick_age_seconds(self, last_tick_ts: str | None) -> int | None:
        if not last_tick_ts:
            return None
        tz = ZoneInfo(self.heartbeat_service.timezone)
        now = datetime.now(tz)
        try:
            tick_dt = datetime.fromisoformat(last_tick_ts)
        except ValueError:
            return None
        return max(0, int((now - tick_dt).total_seconds()))

    def get_label_text(self) -> str:
        state = self._state_snapshot()
        if state.get("paused"):
            status = "PAUSED"
        elif state.get("last_error"):
            status = "ERROR"
        elif state.get("warn_count", 0) > 0:
            status = "WARN"
        else:
            status = "STEADY"

        age = self._tick_age_seconds(state.get("last_tick_ts"))
        age_suffix = "" if age is None else f" (last {age}s)"
        return f"Heartbeat: {status}{age_suffix}"

    def get_status_tooltip(self) -> str:
        state = self._state_snapshot()
        parts = [
            f"Mode: {state.get('mode', 'MONITOR')}",
            f"Last tick: {state.get('last_tick_ts', 'n/a')}",
            f"Last action: {state.get('last_action', 'Idle')}",
        ]
        if state.get("last_error"):
            parts.append(f"Last error: {state['last_error']}")
        return "\n".join(parts)
