from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from heartbeat.state import HeartbeatState


@dataclass
class HeartbeatContext:
    now_dt: datetime
    settings: dict[str, Any]
    state: HeartbeatState


class HeartbeatTask(Protocol):
    name: str
    min_interval_seconds: int
    enabled_flag_name: str | None

    def should_run(self, ctx: HeartbeatContext) -> bool: ...

    def run(self, ctx: HeartbeatContext) -> list[dict[str, Any]]: ...


class TaskRegistry:
    def __init__(self):
        self._tasks: list[HeartbeatTask] = []

    def register(self, task: HeartbeatTask) -> None:
        self._tasks.append(task)

    def list_tasks(self) -> list[HeartbeatTask]:
        return list(self._tasks)
