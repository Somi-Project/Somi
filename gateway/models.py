from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DeliveryMessage:
    user_id: str
    channel: str
    title: str
    body: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or _now_iso())
        return row


@dataclass(frozen=True)
class DeliveryReceipt:
    delivery_id: str
    user_id: str
    channel: str
    status: str
    title: str
    body: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or _now_iso())
        return row
