from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from routing.domain import classify_domain

_ANAPHORA = re.compile(r"\b(it|that|those|them|what about|and what about|how about)\b", re.I)
_TICKER_RE = re.compile(r"\b[A-Z]{1,5}(?:=[XF])?|\^[A-Z]{1,6}|[A-Z0-9]{2,12}USDT\b")


@dataclass
class PrevTurnState:
    domain: str
    query: str
    timestamp: float


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z]{3,}", (text or "").lower())}


def _extract_tickers(text: str) -> set[str]:
    return {m.group(0).upper() for m in _TICKER_RE.finditer(text or "")}


def _topic_overlap(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def can_reuse_evidence(new_text: str, prev: Optional[PrevTurnState], *, max_news_age_s: int = 1800) -> bool:
    if not prev:
        return False
    new_domain, _ = classify_domain(new_text)
    if new_domain != prev.domain:
        return False
    if new_domain == "news" and (time.time() - float(prev.timestamp)) > max_news_age_s:
        return False
    prev_tickers = _extract_tickers(prev.query)
    new_tickers = _extract_tickers(new_text)
    if prev_tickers and new_tickers and prev_tickers != new_tickers:
        return False

    overlap = _topic_overlap(new_text, prev.query)
    if overlap >= 0.18:
        return True
    return bool(_ANAPHORA.search(new_text))
