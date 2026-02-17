from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MemoryEvent:
    event_id: str
    ts: str
    user_id: str
    scope: str
    event_type: str
    claim_id: Optional[str]
    payload: dict


@dataclass
class RetrievedMemory:
    claim_id: str
    content: str
    memory_type: str
    scope: str
    sim: float
    rank_score: float
    ts: str
