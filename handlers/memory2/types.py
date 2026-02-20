from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Event:
    id: str
    ts: str
    event_type: str
    payload: dict
    source: str = "system"
    session_id: Optional[str] = None


@dataclass
class Fact:
    id: str
    ts: str
    entity: str
    key: str
    value: str
    kind: str
    confidence: float
    status: str
    supersedes: Optional[str] = None
    expires_at: Optional[str] = None
    source: str = "user"
    session_id: Optional[str] = None


@dataclass
class Skill:
    id: str
    ts: str
    trigger: str
    steps: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    success: bool = True
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.6
    last_used: Optional[str] = None


@dataclass
class Reminder:
    id: str
    ts: str
    user_id: str
    title: str
    due_ts: str
    status: str
    scope: str = "task"
    details: str = ""
    priority: int = 3
    last_notified_ts: Optional[str] = None
    notify_count: int = 0


@dataclass
class FactCandidate:
    entity: str = "user"
    key: str = ""
    value: str = ""
    kind: str = "preference"
    confidence: float = 0.7
    source: str = "user"
    session_id: Optional[str] = None
    expires_at: Optional[str] = None


@dataclass
class SkillCandidate:
    trigger: str
    steps: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    success: bool = True
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.6
