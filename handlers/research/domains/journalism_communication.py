"""
JournalismCommunicationDomain — 

includes GDELT 2.0 for real-time media tone, mention volume, and coverage trends.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from handlers.research.searxng import search_searxng 
from handlers.research.base import (
    infer_evidence_level,
    make_spans_from_text,
    normalize_query,
    pack_result,
    safe_trim,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0
HTTP_SEM_LIMIT = 6
SRC_SEM_LIMIT = 3

MAX_PER_SOURCE = 8


def _looks_like_journalism(q: str) -> bool:
    ql = (q or "").lower()
    triggers = [
        "journalism", "media", "news", "headline", "reporting", "coverage",
        "propaganda", "misinformation", "disinformation", "fake news",
        "bias", "media bias", "sentiment", "public opinion", "framing",
        "communication", "mass communication", "rhetoric", "discourse",
        "press", "broadcast", "digital media", "social media influence",
    ]
    return any(t in ql for t in triggers)


def _reconstruct_openalex_abstract(inv_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(inv_index, dict):
        return ""
    words = []
    for word, positions in sorted(inv_index.items(), key=lambda x: min(x[1])):
        words.extend([word] * len(positions))
    return " ".join(words)


class JournalismCommunicationDomain:
    DOMAIN = "journalism_communication"

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = float(timeout_s)
        self._http_sem = asyncio.Semaphore(HTTP_SEM_LIMIT)
        self._src_sem = asyncio.Semaphore(SRC_SEM_LIMIT)

    async def search(self, query: str, *, retries: int = 2, backoff_factor: float = 0.5) -> List[Dict[str, Any]]:
        q = normalize_query(query)
        if not q:
            return [self._sentinel("Science search insufficient coverage", "Empty query.")]

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s,
                headers={"User-Agent": "SomiJournalism/1.0"},
                follow_redirects=True,
            ) as client:

                tasks: List[Any] = [
                    self._search_semantic_scholar(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_openalex(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_arxiv(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_gdelt(client, q, retries=retries, backoff_factor=backoff_factor),
                    # NEW: Parallel SearXNG enrichment
                    search_searxng(client, q, max_results=6, domain=self.DOMAIN),
                ]

                gathered = await asyncio.gather(*tasks, return_exceptions=True)

                merged: List[Dict[str, Any]] = []
                for g in gathered:
                    if isinstance(g, list):
                        merged.extend([x for x in g if isinstance(x, dict)])

                non_sentinels = [r for r in merged if not self._is_sentinel_dict(r)]
                merged = non_sentinels or merged

                if not merged:
                    return [self._sentinel(
                        "Science search insufficient coverage",
                        "No relevant journalism/communication data found in academic or GDELT sources.",
                        query=q,
                    )]

                jour = _looks_like_journalism(q)
                for r in merged:
                    src = str(r.get("source") or "")
                    if src == "gdelt":
                        r["intent_alignment"] = 1.2 if jour else 0.95  # Strong boost for media/event queries
                    elif src in ("semanticscholar", "openalex"):
                        r["intent_alignment"] = 1.0 if jour else 0.85
                    elif src == "arxiv":
                        r["intent_alignment"] = 0.90 if jour else 0.80
                    elif src == "crossref":
                        r["intent_alignment"] = 0.75
                    else:
                        r["intent_alignment"] = 0.70

                logger.info(f"JournalismCommunicationDomain returned {len(merged)} results for '{q}'")
                return merged

        except Exception as e:
            logger.warning(f"JournalismCommunicationDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Journalism/communication sources unreachable (network error).",
                query=q,
            )]

    # Sentinels / HTTP helpers — unchanged from previous version

    # Academic sources (Semantic Scholar, OpenAlex, Crossref, arXiv) — unchanged from previous version

    # -----------------------------
    # GDELT 2.0 — NEW: media tone & mention timelines (public, no key)
    # -----------------------------
    async def _search_gdelt(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qq = quote_plus(q)
            # Tone timeline (average tone over time)
            tone_url = f"http://api.gdeltproject.org/api/v2/guides/guides?mode=timelinetone&query={qq}&timespan=5years&format=json"
            # Mention volume timeline
            vol_url = f"http://api.gdeltproject.org/api/v2/guides/guides?mode=timelinevolraw&query={qq}&timespan=5years&format=json"

            tone_js = await self._get_json(client, tone_url, retries=retries, backoff_factor=backoff_factor)
            vol_js = await self._get_json(client, vol_url, retries=retries, backoff_factor=backoff_factor)

            out: List[Dict[str, Any]] = []

            if tone_js and isinstance(tone_js, dict) and tone_js.get("timeline"):
                timeline = tone_js["timeline"][0]["data"] if tone_js["timeline"] else []
                if timeline:
                    dates = [point["date"] for point in timeline[:20]]
                    tones = [point["value"] for point in timeline[:20]]
                    spans = [f"Tone timeline (last ~5 years):"]
                    for d, t in zip(dates, tones):
                        spans.append(f"{d}: average tone {t:.2f}")
                    spans.append("Note: Tone ranges ~ -100 (very negative) to +100 (very positive)")

                    r = pack_result(
                        title=f"GDELT Media Tone Timeline: {q}",
                        url=f"https://blog.gdeltproject.org/?s={qq}",
                        description="Global average tone in news coverage mentioning the query.",
                        source="gdelt",
                        domain=self.DOMAIN,
                        id_type="url",
                        id=tone_url,
                        published="",
                        evidence_level="media_analysis",
                        evidence_spans=spans[:12],
                    )
                    r["volatile"] = True
                    out.append(r)

            if vol_js and isinstance(vol_js, dict) and vol_js.get("timeline"):
                timeline = vol_js["timeline"][0]["data"] if vol_js["timeline"] else []
                if timeline:
                    dates = [point["date"] for point in timeline[:20]]
                    volumes = [point["value"] for point in timeline[:20]]
                    spans = [f"Mention volume timeline (last ~5 years):"]
                    for d, v in zip(dates, volumes):
                        spans.append(f"{d}: {v} articles")
                    spans.append("Higher volume = more global news coverage.")

                    r = pack_result(
                        title=f"GDELT Mention Volume Timeline: {q}",
                        url=f"https://blog.gdeltproject.org/?s={qq}",
                        description="Global article mention counts over time.",
                        source="gdelt",
                        domain=self.DOMAIN,
                        id_type="url",
                        id=vol_url,
                        published="",
                        evidence_level="media_analysis",
                        evidence_spans=spans[:12],
                    )
                    r["volatile"] = True
                    out.append(r)

            return out