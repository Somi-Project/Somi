"""
Shared SearXNG searcher — free, local metasearch fallback/enrichment.
No auth/key required (self-hosted Docker).
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import httpx

from config.settings import SEARXNG_BASE_URL
from handlers.research.base import pack_result, safe_trim

logger = logging.getLogger(__name__)

_SEARXNG_SEM = asyncio.Semaphore(3)

# keep conservative; categories differ between instances and are optional anyway
_ALLOWED_CATEGORIES = {"general", "news", "science", "it", "files", "images", "videos"}


def _pick(res: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


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
    q = (query or "").strip()
    if not q:
        return []

    base = (SEARXNG_BASE_URL or "").strip().rstrip("/")
    if not base:
        logger.debug("SEARXNG_BASE_URL not set; skipping searxng search")
        return []

    cat = category if category in _ALLOWED_CATEGORIES else "general"
    search_url = urljoin(base + "/", "search")

    params = {
        "q": q,
        "format": "json",
        "pageno": 1,
        # categories param is optional; keep it but don't rely on it
        "categories": cat,
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)",
        "Accept": "application/json",
    }

    async with _SEARXNG_SEM:  # Polite global rate limit across concurrent calls
        try:
            r = await client.get(search_url, params=params, headers=headers, timeout=10.0)
            if r.status_code != 200:
                logger.debug(f"SearXNG error {r.status_code} for '{q}'")
                return []
            js = r.json()
        except Exception as e:
            logger.debug(f"SearXNG request failed for '{q}': {e}")
            return []

    raw_results = js.get("results", []) or []
    if not isinstance(raw_results, list):
        return []

    out: List[Dict[str, Any]] = []
    for res in raw_results[: max_results]:
        if not isinstance(res, dict):
            continue

        title = _pick(res, "title") or "SearXNG Result"
        url2 = _pick(res, "url")
        content = _pick(res, "content", "snippet", "description")

        # IMPORTANT: your instance returns publishedDate/pubdate sometimes
        published = _pick(res, "publishedDate", "pubdate", "published_at", "date")

        if not url2:
            continue

        # Put published date into description so the model sees it in-context
        desc = content
        if published:
            if desc:
                desc = f"[{published}] {desc}"
            else:
                desc = f"[{published}]"

        spans = [safe_trim(desc, 300)] if desc else []

        r_dict = pack_result(
            title=title,
            url=url2,
            description=safe_trim(desc, 800),
            source=source_name,
            domain=domain,
            id_type="url",
            id=url2,
            published=published,
            evidence_level="web_search",
            evidence_spans=spans[:6],
        )
        r_dict["volatile"] = True
        out.append(r_dict)

    logger.info(f"SearXNG returned {len(out)} results for '{q}' (category={cat})")
    return out
