from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


OBJECT_KINDS = {
    "User",
    "Conversation",
    "Goal",
    "Reminder",
    "Artifact",
    "Job",
    "System",
    "Channel",
    "Automation",
    "Task",
    "Node",
    "Action",
}

STATUS_BY_KIND = {
    "User": {"active", "inactive"},
    "Conversation": {"active", "idle", "archived"},
    "Goal": {"open", "done", "blocked", "retracted"},
    "Reminder": {"active", "done", "retracted"},
    "Artifact": {"open", "in_progress", "done", "unknown"},
    "Job": {"pending", "running", "verified", "completed", "failed", "cancelled"},
    "System": {"online", "offline", "degraded"},
    "Channel": {"enabled", "disabled", "queued"},
    "Automation": {"active", "paused", "failed", "completed"},
    "Task": {"open", "in_progress", "blocked", "done"},
    "Node": {"online", "offline", "revoked", "pending_pair"},
    "Action": {"pending", "approved", "denied", "running", "completed", "blocked"},
}


def normalize_kind(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "System"
    candidate = raw[:1].upper() + raw[1:]
    return candidate if candidate in OBJECT_KINDS else "System"


def normalize_status(kind: str, value: Any) -> str:
    normalized_kind = normalize_kind(kind)
    raw = str(value or "").strip().lower()
    allowed = STATUS_BY_KIND.get(normalized_kind, {"active"})
    if raw in allowed:
        return raw
    if raw in {"complete", "completed", "verified"} and "completed" in allowed:
        return "completed"
    if raw in {"working", "running"} and "running" in allowed:
        return "running"
    if raw in {"working", "doing"} and "in_progress" in allowed:
        return "in_progress"
    if raw in {"todo", "pending"} and "open" in allowed:
        return "open"
    if raw in {"error"} and "failed" in allowed:
        return "failed"
    return sorted(allowed)[0]


def build_searchable_text(label: str, attributes: dict[str, Any] | None = None) -> str:
    payload = json.dumps(dict(attributes or {}), ensure_ascii=False, sort_keys=True)
    return " ".join(f"{label} {payload}".split())[:4000]


@dataclass(frozen=True)
class OntologyObject:
    object_id: str
    kind: str
    label: str
    status: str
    owner_user_id: str = ""
    thread_id: str = ""
    source: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["kind"] = normalize_kind(self.kind)
        row["status"] = normalize_status(row["kind"], self.status)
        row["searchable_text"] = build_searchable_text(self.label, self.attributes)
        return row


@dataclass(frozen=True)
class OntologyLink:
    from_id: str
    relation: str
    to_id: str
    owner_user_id: str = ""
    thread_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
