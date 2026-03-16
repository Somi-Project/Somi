from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class TimeAnchor:
    kind: Literal["year", "month_year", "date", "range"]
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    date: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    label: str = ""


@dataclass
class QuerySignals:
    explicit: bool
    recency: bool
    volatile: bool
    research: bool
    exactness: bool
    time_anchor: Optional[TimeAnchor]
    domain: str
    is_personal: bool


@dataclass
class QueryPlan:
    mode: Literal["LLM_ONLY", "SEARCH_ONLY", "DUAL"]
    domain: str
    needs_recency: bool
    time_anchor: Optional[TimeAnchor]
    evidence_enabled: bool
    search_query: str
    reason: str
    confidence: float

    def summary(self) -> str:
        anchor = "none"
        if self.time_anchor:
            anchor = self.time_anchor.label or self.time_anchor.kind
        return (
            "QUERY_PLAN:\n"
            f"MODE={self.mode}\n"
            f"DOMAIN={self.domain}\n"
            f"NEEDS_RECENCY={'true' if self.needs_recency else 'false'}\n"
            f"TIME_ANCHOR={anchor}\n"
            f"EVIDENCE_ENABLED={'true' if self.evidence_enabled else 'false'}\n"
            f"REASON={self.reason}"
        )
