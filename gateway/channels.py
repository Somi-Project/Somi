from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Protocol

from .models import DeliveryMessage, DeliveryReceipt


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class DeliveryChannel(Protocol):
    name: str

    def deliver(self, message: DeliveryMessage) -> DeliveryReceipt: ...


class DesktopChannel:
    name = "desktop"

    def __init__(self, root_dir: str | Path = "sessions/delivery") -> None:
        self.root_dir = Path(root_dir)

    def deliver(self, message: DeliveryMessage) -> DeliveryReceipt:
        payload = message.to_record()
        receipt = DeliveryReceipt(
            delivery_id=str(uuid.uuid4()),
            user_id=str(message.user_id),
            channel=self.name,
            status="delivered",
            title=str(message.title),
            body=str(message.body),
            metadata=dict(message.metadata or {}),
        )
        _append_jsonl(self.root_dir / self.name / "inbox.jsonl", payload)
        _append_jsonl(self.root_dir / self.name / "outbox.jsonl", receipt.to_record())
        return receipt


class QueuedFileChannel:
    def __init__(self, name: str, root_dir: str | Path = "sessions/delivery") -> None:
        self.name = str(name)
        self.root_dir = Path(root_dir)

    def deliver(self, message: DeliveryMessage) -> DeliveryReceipt:
        payload = message.to_record()
        receipt = DeliveryReceipt(
            delivery_id=str(uuid.uuid4()),
            user_id=str(message.user_id),
            channel=self.name,
            status="queued",
            title=str(message.title),
            body=str(message.body),
            metadata=dict(message.metadata or {}),
        )
        _append_jsonl(self.root_dir / self.name / "queue.jsonl", payload)
        _append_jsonl(self.root_dir / self.name / "outbox.jsonl", receipt.to_record())
        return receipt
