from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ExecutionTicket:
    job_id: str
    action: str
    commands: list[list[str]]
    cwd: str
    env_overrides: dict[str, str] = field(default_factory=dict)
    allow_network: bool = False
    allow_delete: bool = False
    allow_external_apps: bool = False
    allow_system_wide: bool = False
    paths_rw: list[str] = field(default_factory=list)
    paths_ro: list[str] = field(default_factory=list)
    bulk_targetset_id: str | None = None
    timeout_seconds: int = 30
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def normalize_ticket(ticket: ExecutionTicket) -> dict:
    payload = asdict(ticket)
    payload["commands"] = [list(cmd) for cmd in payload.get("commands", [])]
    payload["paths_rw"] = sorted(payload.get("paths_rw", []))
    payload["paths_ro"] = sorted(payload.get("paths_ro", []))
    payload["env_overrides"] = {
        k: payload["env_overrides"][k] for k in sorted(payload.get("env_overrides", {}))
    }
    return payload


def ticket_hash(ticket: ExecutionTicket) -> str:
    normalized = normalize_ticket(ticket)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
