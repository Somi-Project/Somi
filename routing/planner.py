from __future__ import annotations

import re
from typing import Optional

from routing.followup import PrevTurnState
from routing.signals import extract_signals
from routing.types import QueryPlan, TimeAnchor


def _rewrite_search_query(text: str, anchor: Optional[TimeAnchor], *, include_recency: bool) -> str:
    q = (text or "").strip()
    if anchor and anchor.label and anchor.label.lower() not in q.lower():
        q = f"{q} {anchor.label}".strip()
    if include_recency:
        return q
    q = q.replace(" today", "").replace(" current", "").replace(" latest", "")
    return " ".join(q.split())


def _has_hard_search_request(text: str) -> bool:
    return bool(re.search(r"\b(search|look up|google|find online|check online)\b", text or "", re.I))

def build_query_plan(text: str, prev: Optional[PrevTurnState] = None) -> QueryPlan:
    _ = prev
    signals = extract_signals(text)

    if signals.is_personal:
        return QueryPlan("LLM_ONLY", signals.domain, False, signals.time_anchor, False, "", "personal_query_hardblock", 0.99)

    if signals.time_anchor is not None and not signals.recency and not _has_hard_search_request(text):
        if signals.exactness:
            return QueryPlan("LLM_ONLY", signals.domain, False, signals.time_anchor, False, "", "historical_exactness_internal", 0.91)
        return QueryPlan("LLM_ONLY", signals.domain, False, signals.time_anchor, False, "", "historical_time_anchor", 0.90)

    if signals.explicit or signals.research:
        return QueryPlan("SEARCH_ONLY", signals.domain, signals.recency, signals.time_anchor, True, _rewrite_search_query(text, signals.time_anchor, include_recency=signals.recency), "explicit_sources_or_research", 0.95)

    if signals.recency:
        return QueryPlan("SEARCH_ONLY", signals.domain, True, signals.time_anchor, True, _rewrite_search_query(text, signals.time_anchor, include_recency=True), "explicit_recency", 0.93)

    if signals.volatile and signals.time_anchor is None:
        return QueryPlan("SEARCH_ONLY", signals.domain, True, None, True, _rewrite_search_query(text, None, include_recency=True), "volatile_no_time_anchor", 0.88)

    return QueryPlan("LLM_ONLY", signals.domain, False, None, False, "", "default_internal", 0.70)
