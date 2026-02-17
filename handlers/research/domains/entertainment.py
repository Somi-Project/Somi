"""
EntertainmentDomain — free, no-auth retrieval for entertainment realm:
movies, TV, anime, video games, awards, top lists, ratings trends, popular culture research.

Design goals:
- Blend academic sources (studies on media/entertainment psychology) with pop culture overviews
- Use Wikipedia/MediaWiki API for up-to-date lists (e.g., recent films, top games, anime seasons, awards)
- All sources no-key/public
- Parallel searches
- Graceful sentinel fallback to general web search (which handles volatile news/ratings well)
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


def _looks_like_entertainment(q: str) -> bool:
    """Broad intent detection for entertainment topics"""
    ql = (q or "").lower()
    triggers = [
        "movie", "film", "tv show", "series", "netflix", "disney", "hbo",
        "anime", "manga", "crunchyroll", "myanimelist", "anime season",
        "game", "video game", "gaming", "esports", "steam", "playstation", "xbox", "nintendo",
        "award", "oscars", "emmy", "golden globe", "game awards", "anime awards",
        "top", "highest grossing", "box office", "rating", "imdb", "rotten tomatoes",
        "popular", "trending", "new release", "upcoming",
    ]
    return any(t in ql for t in triggers)


def _reconstruct_openalex_abstract(inv_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(inv_index, dict):
        return ""
    words = []
    for word, positions in sorted(inv_index.items(), key=lambda x: min(x[1])):
        words.extend([word] * len(positions))
    return " ".join(words)


class EntertainmentDomain:
    DOMAIN = "entertainment"

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
                headers={"User-Agent": "SomiEntertainment/1.0"},
                follow_redirects=True,
            ) as client:

                # Parallel: academic + Wikipedia for pop culture lists/overviews
                tasks: List[Any] = [
                    self._search_semantic_scholar(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_openalex(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_arxiv(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_wikipedia(client, q, retries=retries, backoff_factor=backoff_factor),
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
                        "No relevant entertainment data found in academic or Wikipedia sources. Falling back to general search for latest releases/ratings.",
                        query=q,
                    )]

                ent = _looks_like_entertainment(q)
                for r in merged:
                    src = str(r.get("source") or "")
                    if src == "wikipedia":
                        r["intent_alignment"] = 1.2 if ent else 0.95  # Boost for pop culture lists
                    elif src in ("semanticscholar", "openalex"):
                        r["intent_alignment"] = 1.0 if ent else 0.85
                    elif src == "arxiv":
                        r["intent_alignment"] = 0.90 if ent else 0.80
                    elif src == "crossref":
                        r["intent_alignment"] = 0.75
                    else:
                        r["intent_alignment"] = 0.70

                logger.info(f"EntertainmentDomain returned {len(merged)} results for '{q}'")
                return merged

        except Exception as e:
            logger.warning(f"EntertainmentDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Entertainment sources unreachable (network error).",
                query=q,
            )]

    # -----------------------------
    # Sentinels
    # -----------------------------
    def _sentinel(self, title: str, msg: str, *, query: str = "") -> Dict[str, Any]:
        spans = [safe_trim(msg, 260)]
        if query:
            spans.append(safe_trim(f"Query: {query}", 260))

        r = pack_result(
            title=title,
            url="",
            description=msg,
            source="entertainment",
            domain=self.DOMAIN,
            id_type="none",
            id="",
            published="",
            evidence_level="other",
            evidence_spans=spans[:4],
        )
        r["volatile"] = True
        return r

    def _is_sentinel_dict(self, r: Dict[str, Any]) -> bool:
        t = str((r or {}).get("title") or "").lower()
        return ("science search insufficient coverage" in t) or ("science search unavailable" in t)

    # -----------------------------
    # HTTP helpers (robust)
    # -----------------------------
    def _should_retry_status(self, status: int) -> bool:
        return status in (408, 425, 429) or (500 <= status <= 599)

    async def _sleep_backoff(self, attempt: int, backoff_factor: float, retry_after_s: Optional[float] = None) -> None:
        base = backoff_factor * (2 ** attempt)
        sleep_time = min(30.0, max(base, retry_after_s or 0))
        await asyncio.sleep(sleep_time)

    async def _get_json(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[Dict[str, Any]]:
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    r = await client.get(url)
                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = float(r.headers.get("Retry-After", 0)) if r.headers.get("Retry-After", "").isdigit() else None
                        await self._sleep_backoff(attempt, backoff_factor, ra)
                        continue
                    return None
                return r.json()
            except Exception:
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        return None

    async def _get_text(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[str]:
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    r = await client.get(url)
                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = float(r.headers.get("Retry-After", 0)) if r.headers.get("Retry-After", "").isdigit() else None
                        await self._sleep_backoff(attempt, backoff_factor, ra)
                        continue
                    return None
                return r.text
            except Exception:
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        return None

    # Academic sources (Semantic Scholar, OpenAlex, Crossref, arXiv) — same as gamer_brain version

    # -----------------------------
    # Wikipedia — NEW: pop culture lists/overviews (public MediaWiki API, no key)
    # -----------------------------
    async def _search_wikipedia(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            # First: Search for relevant pages
            search_q = quote_plus(q + " list OR awards OR top OR highest grossing OR season")
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={search_q}&srlimit=10&format=json"
            search_js = await self._get_json(client, search_url, retries=retries, backoff_factor=backoff_factor)
            if not search_js:
                return []

            pages = search_js.get("query", {}).get("search", []) or []
            out: List[Dict[str, Any]] = []

            for page in pages[:4]:  # Top 4 relevant
                if not isinstance(page, dict):
                    continue
                title = page.get("title", "")
                if not title:
                    continue

                # Extract page content (intro + key sections)
                extract_url = (
                    f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&titles={quote_plus(title)}&format=json"
                )
                extract_js = await self._get_json(client, extract_url, retries=retries, backoff_factor=backoff_factor)
                if not extract_js:
                    continue

                page_data = list(extract_js.get("query", {}).get("pages", {}).values())
                if not page_data or not page_data[0]:
                    continue
                content = page_data[0].get("extract", "") or ""

                wiki_url = f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"

                spans = make_spans_from_text(content)[:8]
                spans.insert(0, f"Wikipedia overview: {title}")

                r = pack_result(
                    title=f"Entertainment: {title}",
                    url=wiki_url,
                    description=safe_trim(content, 1200),
                    source="wikipedia",
                    domain=self.DOMAIN,
                    id_type="url",
                    id=wiki_url,
                    published="",
                    evidence_level="encyclopedia",
                    evidence_spans=spans[:10],
                )
                r["volatile"] = True
                out.append(r)

            return out