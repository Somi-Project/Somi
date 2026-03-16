from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


TRANSCRIPT_FINAL = "TRANSCRIPT_FINAL"
BARGE_IN = "BARGE_IN"
SPEAK_CHUNK = "SPEAK_CHUNK"
TURN_CANCELLED = "TURN_CANCELLED"


@dataclass(slots=True)
class SpeechEvent:
    type: str
    turn_id: int
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Tiny fan-out event bus backed by asyncio queues."""

    def __init__(self, maxsize: int = 0):
        self._queues: list[asyncio.Queue[SpeechEvent]] = []
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue[SpeechEvent]:
        q: asyncio.Queue[SpeechEvent] = asyncio.Queue(maxsize=self._maxsize)
        self._queues.append(q)
        return q

    async def publish(self, event: SpeechEvent) -> None:
        for q in list(self._queues):
            await q.put(event)
