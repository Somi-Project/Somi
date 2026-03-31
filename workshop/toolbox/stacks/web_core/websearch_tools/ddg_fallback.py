# handlers/websearch_tools/ddg_fallback.py
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List

from duckduckgo_search import DDGS

from .utils import make_result, normalize_query

logger = logging.getLogger(__name__)

# --- Tavily opt-in (activated when TAVILY_API_KEY is set) ---
try:
    from config.settings import TAVILY_API_KEY as _TAVILY_API_KEY
except Exception:
    _TAVILY_API_KEY = ""


def _tavily_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Attempt a Tavily general search; returns [] on any failure."""
    if not _TAVILY_API_KEY:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=_TAVILY_API_KEY)
        resp = client.search(query, max_results=max_results, topic="general")
        out: List[Dict[str, Any]] = []
        for r in resp.get("results") or []:
            out.append(
                make_result(
                    title=r.get("title", "Result"),
                    url=r.get("url", ""),
                    description=(r.get("content", "") or "")[:800],
                    source="tavily",
                    category="general",
                    volatile=False,
                )
            )
        return out
    except Exception as exc:
        logger.debug("Tavily fallback failed: %s", exc)
        return []


def search_ddg(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    q = normalize_query(query)
    if not q:
        return [make_result("Error", "", "Empty query.", "ddg", "general", False)]

    # Try Tavily first when API key is present.
    if _TAVILY_API_KEY:
        tavily_results = _tavily_search(q, max_results=max_results)
        if tavily_results:
            return tavily_results

    # DDG is fragile. Keep it minimal and slow.
    # If it rate-limits, return [] and let the orchestrator degrade gracefully.
    try:
        time.sleep(random.uniform(0.6, 1.3))
        with DDGS() as ddgs:
            hits = []
            for r in ddgs.text(q, max_results=max_results):
                hits.append(r)
            out: List[Dict[str, Any]] = []
            for h in hits[:max_results]:
                out.append(
                    make_result(
                        title=h.get("title", "Result"),
                        url=h.get("href", ""),
                        description=(h.get("body", "") or "")[:800],
                        source="ddg",
                        category="general",
                        volatile=False,
                    )
                )
            return out
    except Exception as e:
        # Many failures here are rate-limit or block; donâ€™t spam logs.
        logger.info(f"DDG fallback failed: {type(e).__name__}")
        return []


