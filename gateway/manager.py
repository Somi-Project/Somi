from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .channels import DeliveryChannel, DesktopChannel, QueuedFileChannel
from .models import DeliveryMessage, DeliveryReceipt


class DeliveryGateway:
    def __init__(self, root_dir: str | Path = "sessions/delivery") -> None:
        self.root_dir = Path(root_dir)
        self._channels: dict[str, DeliveryChannel] = {}
        self.register(DesktopChannel(root_dir=self.root_dir))
        self.register(QueuedFileChannel("heartbeat", root_dir=self.root_dir))
        self.register(QueuedFileChannel("telegram", root_dir=self.root_dir))

    def register(self, channel: DeliveryChannel) -> None:
        self._channels[str(channel.name)] = channel

    def list_channels(self) -> list[str]:
        return sorted(self._channels.keys())

    def deliver(self, channel_name: str, message: DeliveryMessage) -> DeliveryReceipt:
        key = str(channel_name or "").strip().lower()
        if key not in self._channels:
            raise ValueError(f"Unknown delivery channel: {channel_name}")
        return self._channels[key].deliver(message)

    def list_messages(self, channel_name: str, *, box: str = "outbox", limit: int = 20) -> list[dict[str, Any]]:
        path = self.root_dir / str(channel_name or "").strip().lower() / f"{box}.jsonl"
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows[-max(1, int(limit or 20)) :]
