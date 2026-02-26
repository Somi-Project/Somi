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
    allowed_capabilities: list[str] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    output_size_cap_kb: int = 512
    created_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Back-compat flags
    allow_network: bool = False
    allow_delete: bool = False
    allow_external_apps: bool = False
    allow_system_wide: bool = False
    paths_rw: list[str] = field(default_factory=list)
    paths_ro: list[str] = field(default_factory=list)
    bulk_targetset_id: str | None = None


def normalize_ticket(ticket: ExecutionTicket) -> dict:
    payload = asdict(ticket)
    payload["commands"] = [list(cmd) for cmd in payload.get("commands", [])]
    payload["paths_rw"] = sorted(payload.get("paths_rw", []))
    payload["paths_ro"] = sorted(payload.get("paths_ro", []))
    payload["allowed_capabilities"] = sorted(payload.get("allowed_capabilities", []))
    payload["env_overrides"] = {k: payload["env_overrides"][k] for k in sorted(payload.get("env_overrides", {}))}
    # keep hash deterministic for semantically identical tickets across turns
    payload.pop("created_timestamp", None)
    return payload


def ticket_hash(ticket: ExecutionTicket) -> str:
    raw = json.dumps(normalize_ticket(ticket), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_ticket_integrity(ticket: ExecutionTicket, expected_hash: str) -> None:
    if ticket_hash(ticket) != expected_hash:
        raise ValueError("Execution ticket mutation detected")
