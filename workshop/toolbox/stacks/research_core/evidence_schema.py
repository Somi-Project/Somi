from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceItem:
    id: str
    title: str
    url: str
    source_type: str
    published_date: Optional[str]
    retrieved_at: str
    snippet: Optional[str] = None
    content_excerpt: Optional[str] = None
    identifiers: Dict[str, str] = field(default_factory=dict)
    domain: Optional[str] = None
    score: float = 0.0
    score_breakdown: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Claim:
    id: str
    text: str
    scope: Optional[str]
    numbers: Optional[Dict[str, Any]]
    supporting_item_ids: List[str] = field(default_factory=list)
    contradicting_item_ids: List[str] = field(default_factory=list)
    confidence: str = "low"
    confidence_score: float = 0.0


@dataclass
class EvidenceBundle:
    question: str
    queries: List[str]
    items: List[EvidenceItem]
    claims: List[Claim]
    conflicts: List[Dict[str, Any]]
    calculations: List[Dict[str, Any]]
    answer: str
    limitations: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

