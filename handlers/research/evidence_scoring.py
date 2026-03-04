from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple
from urllib.parse import urlparse

from handlers.research.evidence_schema import EvidenceItem

_SOURCE_WEIGHTS = {
    "official": 1.0,
    "academic": 0.9,
    "reputable_news": 0.7,
    "reference": 0.65,
    "vendor": 0.45,
    "blog": 0.3,
    "forum": 0.2,
    "unknown": 0.25,
}


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 2}


def classify_source_type(url: str, *, provider_hint: str = "") -> str:
    host = (urlparse(url).netloc or "").lower()
    hint = (provider_hint or "").lower()
    if any(h in host for h in (".gov", "who.int", "cdc.gov", "nice.org.uk")):
        return "official"
    if any(h in host for h in ("nature.com", "nejm.org", "thelancet.com", "jamanetwork.com")):
        return "academic"
    if any(h in host for h in ("arxiv.org", "pubmed", "semanticscholar.org")) or hint in {"pubmed", "arxiv", "semantic_scholar"}:
        return "academic"
    if any(h in host for h in ("wikipedia.org", "britannica.com")):
        return "reference"
    if any(h in host for h in ("reuters.com", "apnews.com", "bbc.com", "bbc.co.uk")):
        return "reputable_news"
    if any(h in host for h in ("docs.", "developer.", "support.")):
        return "vendor"
    if any(h in host for h in ("reddit.com", "forum", "community.")):
        return "forum"
    if any(h in host for h in ("blog", "medium.com", "substack.com")):
        return "blog"
    return "unknown"


def _recency_bonus(published_date: str | None, needs_recency: bool) -> float:
    if not needs_recency:
        return 0.0
    if not published_date:
        return -0.2
    try:
        dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
    except Exception:
        return -0.1
    now = datetime.now(timezone.utc)
    days = max(0.0, (now - dt.astimezone(timezone.utc)).days)
    if days <= 30:
        return 0.25
    if days <= 365:
        return 0.12
    return -0.05


def score_item(item: EvidenceItem, *, question: str, needs_recency: bool) -> Tuple[float, Dict[str, float]]:
    base_trust = _SOURCE_WEIGHTS.get(item.source_type, _SOURCE_WEIGHTS["unknown"])
    q_toks = _tokenize(question)
    txt = " ".join(filter(None, [item.title, item.snippet or "", item.content_excerpt or ""]))
    d_toks = _tokenize(txt)
    overlap = len(q_toks & d_toks)
    relevance = min(0.7, overlap / max(1, len(q_toks)))
    recency = _recency_bonus(item.published_date, needs_recency)
    penalties = 0.0
    if not (item.content_excerpt or "") and not (item.snippet or ""):
        penalties += 0.12
    if len((item.content_excerpt or "").strip()) < 140:
        penalties += 0.08
    if item.source_type in {"blog", "forum", "unknown"}:
        penalties += 0.06

    score = max(0.0, min(1.0, base_trust + relevance + recency - penalties))
    breakdown = {
        "base_trust": round(base_trust, 4),
        "relevance": round(relevance, 4),
        "recency_bonus": round(recency, 4),
        "penalties": round(penalties, 4),
    }
    return score, breakdown


def score_items(items: Iterable[EvidenceItem], *, question: str, needs_recency: bool) -> list[EvidenceItem]:
    out = []
    for item in items:
        item.score, item.score_breakdown = score_item(item, question=question, needs_recency=needs_recency)
        out.append(item)
    out.sort(key=lambda x: x.score, reverse=True)
    return out
