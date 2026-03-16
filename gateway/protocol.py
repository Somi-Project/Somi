from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _listify(values: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        item = str(value or "").strip().lower()
        if item and item not in out:
            out.append(item)
    return out


@dataclass(frozen=True)
class GatewaySessionRecord:
    session_id: str
    user_id: str
    surface: str
    client_id: str
    client_label: str = ""
    platform: str = ""
    auth_mode: str = "local"
    trust_level: str = "trusted_local"
    status: str = "online"
    created_at: str = ""
    last_seen_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or utcnow_iso())
        row["last_seen_at"] = str(self.last_seen_at or row["created_at"])
        return row


@dataclass(frozen=True)
class GatewayPresenceRecord:
    session_id: str
    client_id: str
    user_id: str
    surface: str
    status: str = "online"
    activity: str = ""
    detail: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["updated_at"] = str(self.updated_at or utcnow_iso())
        return row


@dataclass(frozen=True)
class GatewayHealthRecord:
    service_id: str
    surface: str
    status: str
    summary: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["updated_at"] = str(self.updated_at or utcnow_iso())
        return row


@dataclass(frozen=True)
class GatewayEventRecord:
    event_id: str
    event_type: str
    surface: str
    title: str
    body: str = ""
    level: str = "info"
    user_id: str = ""
    session_id: str = ""
    client_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or utcnow_iso())
        return row


@dataclass(frozen=True)
class GatewayPairingRecord:
    pairing_id: str
    code: str
    requested_surface: str
    client_label: str = ""
    platform: str = ""
    owner_user_id: str = "default_user"
    session_id: str = ""
    status: str = "pending"
    scopes: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or utcnow_iso())
        row["updated_at"] = str(self.updated_at or row["created_at"])
        row["scopes"] = _listify(self.scopes)
        return row


@dataclass(frozen=True)
class GatewayNodeRecord:
    node_id: str
    session_id: str
    user_id: str
    node_type: str
    client_label: str = ""
    platform: str = ""
    trust_level: str = "untrusted_remote"
    status: str = "pending"
    capabilities: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["created_at"] = str(self.created_at or utcnow_iso())
        row["updated_at"] = str(self.updated_at or row["created_at"])
        row["capabilities"] = _listify(self.capabilities)
        return row
