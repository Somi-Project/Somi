from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _dedupe_strings(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(items or []):
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


@dataclass
class CodingWorkspaceSnapshot:
    workspace_id: str
    title: str
    root_path: str
    user_id: str
    language: str = "python"
    profile_key: str = "python"
    profile_display_name: str = "Python"
    runtime_profile: str = "python"
    sandbox_backend: str = ""
    entrypoint: str = ""
    manifest_path: str = ""
    recent_files: list[str] = field(default_factory=list)
    available_runtimes: list[dict[str, Any]] = field(default_factory=list)
    suggested_commands: list[str] = field(default_factory=list)
    starter_files: list[str] = field(default_factory=list)
    run_command: str = ""
    test_command: str = ""
    workspace_markers: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.workspace_id = str(self.workspace_id or "").strip()
        self.title = str(self.title or "").strip() or "Coding Workspace"
        self.root_path = str(self.root_path or "").strip()
        self.user_id = str(self.user_id or "default_user").strip() or "default_user"
        self.language = str(self.language or "python").strip().lower() or "python"
        self.profile_key = str(self.profile_key or self.language or "python").strip().lower() or "python"
        self.profile_display_name = str(self.profile_display_name or self.profile_key.title()).strip() or self.profile_key.title()
        self.runtime_profile = str(self.runtime_profile or self.profile_key or "python").strip().lower() or "python"
        self.sandbox_backend = str(self.sandbox_backend or "").strip().lower()
        self.entrypoint = str(self.entrypoint or "").strip()
        self.manifest_path = str(self.manifest_path or "").strip()
        self.recent_files = _dedupe_strings(list(self.recent_files or []))
        self.available_runtimes = [dict(row) for row in list(self.available_runtimes or []) if isinstance(row, dict)]
        self.suggested_commands = _dedupe_strings(list(self.suggested_commands or []))
        self.starter_files = _dedupe_strings(list(self.starter_files or []))
        self.run_command = str(self.run_command or "").strip()
        self.test_command = str(self.test_command or "").strip()
        self.workspace_markers = [dict(row) for row in list(self.workspace_markers or []) if isinstance(row, dict)]
        self.capabilities = _dedupe_strings(list(self.capabilities or []))
        self.metadata = dict(self.metadata or {})
        self.created_at = str(self.created_at or "").strip()
        self.updated_at = str(self.updated_at or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "title": str(self.title),
            "root_path": str(self.root_path),
            "user_id": str(self.user_id),
            "language": str(self.language),
            "profile_key": str(self.profile_key),
            "profile_display_name": str(self.profile_display_name),
            "runtime_profile": str(self.runtime_profile),
            "sandbox_backend": str(self.sandbox_backend),
            "entrypoint": str(self.entrypoint),
            "manifest_path": str(self.manifest_path),
            "recent_files": list(self.recent_files),
            "available_runtimes": list(self.available_runtimes),
            "suggested_commands": list(self.suggested_commands),
            "starter_files": list(self.starter_files),
            "run_command": str(self.run_command),
            "test_command": str(self.test_command),
            "workspace_markers": list(self.workspace_markers),
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata or {}),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


@dataclass
class CodingSessionSnapshot:
    session_id: str
    user_id: str
    source: str
    title: str
    objective: str
    status: str
    coding_model: str
    agent_profile: str
    workspace: CodingWorkspaceSnapshot
    welcome_text: str = ""
    last_prompt: str = ""
    turn_count: int = 0
    tags: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id or "").strip()
        self.user_id = str(self.user_id or "default_user").strip() or "default_user"
        self.source = str(self.source or "chat").strip().lower() or "chat"
        self.title = str(self.title or "").strip() or "Coding Session"
        self.objective = str(self.objective or "").strip()
        self.status = str(self.status or "active").strip().lower() or "active"
        self.coding_model = str(self.coding_model or "").strip()
        self.agent_profile = str(self.agent_profile or "coding_worker").strip()
        self.welcome_text = str(self.welcome_text or "").strip()
        self.last_prompt = str(self.last_prompt or "").strip()
        self.turn_count = max(0, int(self.turn_count or 0))
        self.tags = _dedupe_strings(list(self.tags or []))
        self.next_actions = _dedupe_strings(list(self.next_actions or []))
        self.metadata = dict(self.metadata or {})
        self.created_at = str(self.created_at or "").strip()
        self.updated_at = str(self.updated_at or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "source": str(self.source),
            "title": str(self.title),
            "objective": str(self.objective),
            "status": str(self.status),
            "coding_model": str(self.coding_model),
            "agent_profile": str(self.agent_profile),
            "workspace": self.workspace.to_dict(),
            "welcome_text": str(self.welcome_text),
            "last_prompt": str(self.last_prompt),
            "turn_count": int(self.turn_count),
            "tags": list(self.tags),
            "next_actions": list(self.next_actions),
            "metadata": dict(self.metadata or {}),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CodingSessionSnapshot":
        workspace = CodingWorkspaceSnapshot(**dict(payload.get("workspace") or {}))
        data = dict(payload or {})
        data["workspace"] = workspace
        return cls(**data)
