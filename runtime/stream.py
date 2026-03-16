from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class StepEvent:
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StepSink(Protocol):
    def emit(self, event: StepEvent) -> None:
        ...


class PrintStepSink:
    def emit(self, event: StepEvent) -> None:
        print(f"[{event.kind}] {event.message}")
