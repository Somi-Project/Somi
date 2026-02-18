from __future__ import annotations

import hashlib
import queue
import threading
from collections import deque
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def _now_iso(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).isoformat()


def make_event(
    level: str,
    type: str,
    title: str,
    detail: str | None = None,
    actions: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "ts": _now_iso(timezone),
        "source": "heartbeat",
        "level": level,
        "type": type,
        "title": title,
    }
    if detail:
        event["detail"] = detail
    if actions:
        event["actions"] = actions
    if meta:
        event["meta"] = meta
    return event


class EventRingBuffer:
    def __init__(self, maxlen: int):
        self._events = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)

    def get_last(self, n: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[-n:]

    def to_list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


class EventQueue:
    def __init__(self):
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()

    def put(self, event: dict[str, Any]) -> None:
        self._queue.put(event)

    def drain(self, max_n: int | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            if max_n is not None and len(items) >= max_n:
                break
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items


def event_signature(event: dict[str, Any]) -> str:
    detail = event.get("detail", "")
    normalized = " ".join(str(detail).split()).lower()
    detail_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest() if normalized else "-"
    raw = f"{event.get('level','')}|{event.get('type','')}|{event.get('title','')}|{detail_hash}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
