from __future__ import annotations

import re
from datetime import datetime

from routing.query_plan import QueryPlan

_RECENCY_CUES = re.compile(r"\b(today|now|current|latest|this week|breaking|update|as of)\b", re.IGNORECASE)
_EXPLICIT_SEARCH_CUES = re.compile(r"\b(search|look up|google|find online|check online|verify)\b", re.IGNORECASE)
_EXACTNESS_CUES = re.compile(
    r"\b(exact|with sources|cite|links|closing price|on\s+\d{4}-\d{2}-\d{2}|highest\/?lowest on)\b",
    re.IGNORECASE,
)
_DOMAIN_FINANCE = re.compile(r"\b(price|prices|quote|quotes|bitcoin|btc|eth|stock|forex|fx|market|closing price)\b", re.IGNORECASE)
_DOMAIN_WEATHER = re.compile(r"\b(weather|forecast|temperature|rain|humidity|wind|sunrise|sunset)\b", re.IGNORECASE)
_DOMAIN_NEWS = re.compile(r"\b(news|breaking|headline|headlines|current events)\b", re.IGNORECASE)
_DOMAIN_SPORTS = re.compile(r"\b(score|scores|schedule|match|game|fixture|standings|sports)\b", re.IGNORECASE)
_DOMAIN_SOFTWARE = re.compile(r"\b(version|release|released|changelog|patch)\b", re.IGNORECASE)
_RECENCY_REQUIRED_DOMAIN = re.compile(
    r"\b(prices?|quotes?|weather|news|scores?|schedule|current\s+ceo|current\s+president|releases?|versions?)\b",
    re.IGNORECASE,
)
_YEAR_RANGE = re.compile(r"\bbetween\s+(19\d{2}|20\d{2})\s*[-–]\s*(19\d{2}|20\d{2})\b|\bfrom\s+(19\d{2}|20\d{2})\s+to\s+(19\d{2}|20\d{2})\b", re.IGNORECASE)
_DATE_ANCHOR = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_YEAR_IN = re.compile(r"\bin\s+(19\d{2}|20\d{2})\b", re.IGNORECASE)
_ANY_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _detect_domain(text: str) -> str:
    if _DOMAIN_FINANCE.search(text):
        return "finance"
    if _DOMAIN_WEATHER.search(text):
        return "weather"
    if _DOMAIN_NEWS.search(text):
        return "news"
    if _DOMAIN_SPORTS.search(text):
        return "sports"
    if _DOMAIN_SOFTWARE.search(text):
        return "software"
    return "general"


def _extract_time_anchor(text: str):
    m_date = _DATE_ANCHOR.search(text)
    if m_date:
        return {"date": m_date.group(1)}

    m_range = _YEAR_RANGE.search(text)
    if m_range:
        years = [int(y) for y in m_range.groups() if y]
        if len(years) == 2:
            return {"start_year": min(years), "end_year": max(years)}

    m_in = _YEAR_IN.search(text)
    if m_in:
        return {"year": int(m_in.group(1))}

    return None


def _rewrite_search_query(user_text: str, domain: str, time_anchor) -> str:
    q = (user_text or "").strip()
    if time_anchor:
        if "date" in time_anchor and time_anchor["date"] not in q:
            q = f"{q} on {time_anchor['date']}"
        elif "year" in time_anchor and str(time_anchor["year"]) not in q:
            q = f"{q} in {time_anchor['year']}"
        elif "start_year" in time_anchor:
            y = f"{time_anchor['start_year']}-{time_anchor['end_year']}"
            if y not in q:
                q = f"{q} from {time_anchor['start_year']} to {time_anchor['end_year']}"

    if domain == "finance" and "closing price" in q.lower() and time_anchor and "date" in time_anchor:
        return f"{q} historical closing price {time_anchor['date']}"
    if domain == "finance" and time_anchor and "year" in time_anchor:
        return f"{q} yearly high low {time_anchor['year']}"
    return q


def build_query_plan(user_text: str) -> QueryPlan:
    text = (user_text or "").strip()
    text_l = text.lower()
    domain = _detect_domain(text)
    current_year = datetime.utcnow().year
    time_anchor = _extract_time_anchor(text_l)

    # C) Exactness/citations override
    if _EXACTNESS_CUES.search(text_l):
        rewritten = _rewrite_search_query(text, domain, time_anchor)
        return QueryPlan(
            mode="SEARCH_ONLY",
            needs_recency=False,
            time_anchor=time_anchor,
            domain=domain,
            evidence_enabled=True,
            rewritten_search_query=rewritten,
            reason="exactness_or_citations_override",
        )

    # Explicit tool request override
    if _EXPLICIT_SEARCH_CUES.search(text_l):
        rewritten = _rewrite_search_query(text, domain, time_anchor)
        return QueryPlan(
            mode="SEARCH_ONLY",
            needs_recency=bool(_RECENCY_CUES.search(text_l) or _RECENCY_REQUIRED_DOMAIN.search(text_l)),
            time_anchor=time_anchor,
            domain=domain,
            evidence_enabled=True,
            rewritten_search_query=rewritten,
            reason="explicit_search_requested",
        )

    # B) Explicit past year / closed range
    if time_anchor:
        anchor_years = []
        if "year" in time_anchor:
            anchor_years = [int(time_anchor["year"])]
        elif "start_year" in time_anchor and "end_year" in time_anchor:
            anchor_years = [int(time_anchor["start_year"]), int(time_anchor["end_year"])]
        if anchor_years and max(anchor_years) < current_year:
            return QueryPlan(
                mode="LLM_ONLY",
                needs_recency=False,
                time_anchor=time_anchor,
                domain=domain,
                evidence_enabled=False,
                rewritten_search_query="",
                reason="historical_year_detected",
            )

    any_year = _ANY_YEAR.search(text_l)
    if any_year and int(any_year.group(1)) < current_year:
        return QueryPlan(
            mode="LLM_ONLY",
            needs_recency=False,
            time_anchor={"year": int(any_year.group(1))},
            domain=domain,
            evidence_enabled=False,
            rewritten_search_query="",
            reason="historical_year_detected",
        )

    # A) Recency required
    if _RECENCY_CUES.search(text_l) or _RECENCY_REQUIRED_DOMAIN.search(text_l):
        rewritten = _rewrite_search_query(text, domain, time_anchor)
        return QueryPlan(
            mode="SEARCH_ONLY",
            needs_recency=True,
            time_anchor=time_anchor,
            domain=domain,
            evidence_enabled=True,
            rewritten_search_query=rewritten,
            reason="recency_required",
        )

    # D) Default
    return QueryPlan(
        mode="LLM_ONLY",
        needs_recency=False,
        time_anchor=time_anchor,
        domain=domain,
        evidence_enabled=False,
        rewritten_search_query="",
        reason="default_llm_only",
    )
