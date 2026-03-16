from __future__ import annotations

import re

from routing.domain import classify_domain
from routing.timeparse import extract_time_anchor
from routing.types import QuerySignals

_EXPLICIT = re.compile(r"\b(search|look up|google|find online|check online|sources?|cite|link|verify|confirm)\b", re.I)
_RECENCY = re.compile(r"\b(latest|current|today|now|right now|this week|updated|breaking|live|recent)\b", re.I)
_VOLATILE = re.compile(r"\b(price|quote|market|stock|shares|bitcoin|btc|eth|oil|wti|brent|fx|exchange rate|weather|forecast|temperature|rain|humidity|wind|news|headline|current events)\b", re.I)
_RESEARCH = re.compile(r"\b(paper|study|pubmed|pmid|doi|arxiv|guideline|systematic review|meta-analysis|clinical trial|nct\d*)\b", re.I)
_EXACTNESS = re.compile(r"\b(exact|precisely|closing|close|open|high|low|with sources|cite|on\s+\d{4}-\d{2}-\d{2})\b", re.I)
_PERSONAL = re.compile(r"\b(what'?s my|my goals?|my reminders?|remind me|what do you remember about me|my state|my memory)\b", re.I)


def extract_signals(text: str) -> QuerySignals:
    raw = str(text or "")
    domain, _ = classify_domain(raw)
    return QuerySignals(
        explicit=bool(_EXPLICIT.search(raw)),
        recency=bool(_RECENCY.search(raw)),
        volatile=bool(_VOLATILE.search(raw)),
        research=bool(_RESEARCH.search(raw)),
        exactness=bool(_EXACTNESS.search(raw)),
        time_anchor=extract_time_anchor(raw),
        domain=domain,
        is_personal=bool(_PERSONAL.search(raw)),
    )
