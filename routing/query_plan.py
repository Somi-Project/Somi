from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Union


TimeAnchor = Optional[Union[Dict[str, int], Dict[str, str]]]


@dataclass
class QueryPlan:
    mode: Literal["LLM_ONLY", "SEARCH_ONLY", "DUAL"]
    needs_recency: bool
    time_anchor: TimeAnchor
    domain: str
    evidence_enabled: bool
    rewritten_search_query: str
    reason: str

    def summary(self) -> str:
        anchor = "none"
        if self.time_anchor is not None:
            if "year" in self.time_anchor:
                anchor = str(self.time_anchor["year"])
            elif "start_year" in self.time_anchor and "end_year" in self.time_anchor:
                anchor = f"{self.time_anchor['start_year']}-{self.time_anchor['end_year']}"
            elif "date" in self.time_anchor:
                anchor = str(self.time_anchor["date"])
        return (
            "QUERY_PLAN:\n"
            f"- MODE: {self.mode}\n"
            f"- NEEDS_RECENCY: {'true' if self.needs_recency else 'false'}\n"
            f"- TIME_ANCHOR: {anchor}\n"
            f"- DOMAIN: {self.domain}\n"
            f"- EVIDENCE_ENABLED: {'true' if self.evidence_enabled else 'false'}\n"
            f"- REASON: {self.reason}"
        )

