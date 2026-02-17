"""
Shared SearXNG searcher — free, local metasearch fallback/enrichment.
No auth/key required (self-hosted Docker).
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus

import httpx

from handlers.research.base import pack_result, safe_trim

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8080"  # Change if your Docker port/host differs


async def search_searxng(
    client: httpx.AsyncClient,
    query: str,
    *,
    max_results: int = 8,
    category: str = "general",
    source_name: str = "searxng",
    domain: str = "general",
) -> List[Dict[str, Any]]:
    """
    Shared async SearXNG search — returns pack_result-compatible dicts.
    """
    async with asyncio.Semaphore(3):  # Polite rate limit
        qq = quote_plus(query)
        url = f"{SEARXNG_URL}/search?q={qq}&format=json&categories={category}&pageno=1"
        try:
            r = await client.get(url, timeout=10.0)
            if r.status_code != 200:
                logger.debug(f"SearXNG error {r.status_code} for '{query}'")
                return []
            js = r.json()
        except Exception as e:
            logger.debug(f"SearXNG request failed for '{query}': {e}")
            return []

        results = js.get("results", [])[:max_results]
        out: List[Dict[str, Any]] = []
        for res in results:
            if not isinstance(res, dict):
                continue
            title = str(res.get("title") or "Untitled").strip()
            url2 = str(res.get("url") or "").strip()
            content = str(res.get("content") or res.get("snippet") or "").strip()
            if not title and not url2:
                continue

            spans = [safe_trim(content, 300)] if content else []

            r_dict = pack_result(
                title=title or "SearXNG Result",
                url=url2,
                description=safe_trim(content, 800),
                source=source_name,
                domain=domain,
                id_type="url",
                id=url2,
                published="",
                evidence_level="web_search",
                evidence_spans=spans[:6],
            )
            r_dict["volatile"] = True
            out.append(r_dict)

        logger.info(f"SearXNG returned {len(out)} results for '{query}'")
        return out