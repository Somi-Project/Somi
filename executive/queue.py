from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ExecutiveQueue:
    def __init__(self, queue_path: str = "executive/queue.json", history_path: str = "executive/history.jsonl") -> None:
        self.queue_path = Path(queue_path)
        self.history_path = Path(history_path)
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_path.exists():
            self.save([])

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def _append_history(self, event: str, payload: dict) -> None:
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, **payload}) + "\n")

    def list(self) -> list[dict]:
        if not self.queue_path.exists():
            self.save([])
            return []
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stamp = str(int(time.time()))
            broken = self.queue_path.with_suffix(self.queue_path.suffix + f".{stamp}.broken")
            self.queue_path.replace(broken)
            self._append_history("queue_recovered", {"from": str(broken)})
            self.save([])
            return []
        if not isinstance(data, list):
            self._append_history("queue_recovered", {"from": "non_list_payload"})
            self.save([])
            return []
        return data

    def save(self, items: list[dict]) -> None:
        self._atomic_write_json(self.queue_path, items)

    def push(self, item: dict) -> None:
        items = self.list()
        items.append(item)
        self.save(items)
        self._append_history("push", {"item": item})

    def set_state(self, intent_id: str, state: str) -> dict:
        items = self.list()
        for item in items:
            if item.get("intent_id") == intent_id:
                item["state"] = state
                self.save(items)
                self._append_history("state_change", {"intent_id": intent_id, "state": state})
                return item
        raise ValueError("intent not found")
