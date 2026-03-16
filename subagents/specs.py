from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any


def _safe_text(value: Any, *, max_len: int = 600) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _safe_key(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value or "").strip().lower())[:80]


def _dedupe_strings(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
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


def new_subagent_run_id(prefix: str = "subagent") -> str:
    stem = _safe_key(prefix) or "subagent"
    return f"{stem}_{uuid.uuid4().hex[:12]}"


def build_subagent_thread_id(thread_id: str, run_id: str) -> str:
    base = _safe_key(thread_id) or "general"
    return f"{base}::subagent::{_safe_key(run_id) or 'run'}"


@dataclass(frozen=True)
class SubagentProfile:
    key: str
    display_name: str
    description: str
    default_allowed_tools: tuple[str, ...] = ()
    default_max_turns: int = 2
    default_backend: str = "local"
    default_timeout_seconds: int = 90
    default_budget_tokens: int = 3000
    toolsets: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": str(self.key),
            "display_name": str(self.display_name),
            "description": str(self.description),
            "default_allowed_tools": list(self.default_allowed_tools),
            "default_max_turns": int(self.default_max_turns),
            "default_backend": str(self.default_backend),
            "default_timeout_seconds": int(self.default_timeout_seconds),
            "default_budget_tokens": int(self.default_budget_tokens),
            "toolsets": list(self.toolsets),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class SubagentRunSpec:
    profile_key: str
    objective: str
    user_id: str
    thread_id: str
    allowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 2
    backend: str = "local"
    timeout_seconds: int = 90
    budget_tokens: int = 3000
    parent_turn_id: int | None = None
    parent_session_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=new_subagent_run_id)
    child_thread_id: str = ""

    def __post_init__(self) -> None:
        self.profile_key = _safe_key(self.profile_key) or "research_scout"
        self.objective = _safe_text(self.objective, max_len=1200)
        self.user_id = str(self.user_id or "default_user").strip() or "default_user"
        self.thread_id = str(self.thread_id or "general").strip() or "general"
        self.allowed_tools = _dedupe_strings(list(self.allowed_tools or []))
        self.max_turns = max(1, min(int(self.max_turns or 1), 8))
        self.backend = str(self.backend or "local").strip().lower() or "local"
        self.timeout_seconds = max(5, min(int(self.timeout_seconds or 90), 900))
        self.budget_tokens = max(256, min(int(self.budget_tokens or 3000), 64000))
        self.parent_session_id = str(self.parent_session_id or "").strip()
        self.artifact_refs = _dedupe_strings(list(self.artifact_refs or []))
        self.metadata = dict(self.metadata or {})
        self.run_id = _safe_key(self.run_id) or new_subagent_run_id(self.profile_key)
        if not self.child_thread_id:
            self.child_thread_id = build_subagent_thread_id(self.thread_id, self.run_id)
        else:
            self.child_thread_id = str(self.child_thread_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "profile_key": str(self.profile_key),
            "objective": str(self.objective),
            "user_id": str(self.user_id),
            "thread_id": str(self.thread_id),
            "child_thread_id": str(self.child_thread_id),
            "allowed_tools": list(self.allowed_tools),
            "max_turns": int(self.max_turns),
            "backend": str(self.backend),
            "timeout_seconds": int(self.timeout_seconds),
            "budget_tokens": int(self.budget_tokens),
            "parent_turn_id": self.parent_turn_id,
            "parent_session_id": str(self.parent_session_id),
            "artifact_refs": list(self.artifact_refs),
            "metadata": dict(self.metadata or {}),
        }
