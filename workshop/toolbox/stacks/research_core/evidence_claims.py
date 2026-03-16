from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Dict, List, Optional

from workshop.toolbox.stacks.research_core.evidence_schema import EvidenceItem

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NUM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(%|percent|mg|kg|g|years?|days?|hours?)?\b", re.IGNORECASE)


@dataclass
class ClaimCandidate:
    text: str
    item_id: str
    scope: Optional[str] = None
    numbers: Optional[Dict[str, Any]] = None


def _claim_id(text: str) -> str:
    return sha1((text or "").strip().lower().encode("utf-8", errors="ignore")).hexdigest()[:16]


def extract_claim_candidates(items: List[EvidenceItem], *, max_claims_per_item: int = 5) -> List[ClaimCandidate]:
    out: List[ClaimCandidate] = []
    keywords = {"increase", "decrease", "effective", "risk", "guideline", "recommend", "associated", "improves", "reduces"}

    for item in items:
        text = (item.content_excerpt or item.snippet or "").strip()
        if not text:
            continue
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 40]
        picked = 0
        for s in sentences:
            sl = s.lower()
            nums = _NUM_RE.findall(s)
            if not (any(k in sl for k in keywords) or nums):
                continue
            payload = None
            if nums:
                payload = {"values": [{"value": float(v), "unit": (u or "").lower()} for v, u in nums[:3]]}
            out.append(ClaimCandidate(text=s[:320], item_id=item.id, numbers=payload))
            picked += 1
            if picked >= max_claims_per_item:
                break
    return out


def claim_candidate_id(c: ClaimCandidate) -> str:
    return _claim_id(f"{c.text}|{c.item_id}")

