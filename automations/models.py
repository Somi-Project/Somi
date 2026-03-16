from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ScheduleSpec:
    kind: str
    timezone: str
    source_text: str
    interval_hours: int = 0
    days_of_week: list[int] = field(default_factory=list)
    hour: int = 9
    minute: int = 0
    next_run_at: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutomationSpec:
    automation_id: str
    user_id: str
    name: str
    automation_type: str
    target_channel: str
    schedule: ScheduleSpec
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    last_run_at: str = ""

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or _now_iso())
        row["updated_at"] = str(self.updated_at or row["created_at"])
        return row


@dataclass(frozen=True)
class AutomationRun:
    run_id: str
    automation_id: str
    user_id: str
    status: str
    target_channel: str
    delivery_status: str
    output_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    completed_at: str = ""

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or _now_iso())
        row["completed_at"] = str(self.completed_at or row["created_at"])
        return row
