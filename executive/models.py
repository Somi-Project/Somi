from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Intent:
    intent_id: str
    action: str
    payload: dict
    state: IntentState = IntentState.PENDING
