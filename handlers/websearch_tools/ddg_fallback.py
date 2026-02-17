# handlers/websearch_tools/ddg_fallback.py
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List

from duckduckgo_search import DDGS

from .utils import make_result, normalize_query

logger = logging.getLogger(__name__)

def search_ddg(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    q = normalize_query(query)
    if not q:
        return [make_result("Error", "", "Empty query.", "ddg", "general", False)]

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
        # Many failures here are rate-limit or block; don’t spam logs.
        logger.info(f"DDG fallback failed: {type(e).__name__}")
        return []
