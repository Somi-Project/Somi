from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import httpx
from duckduckgo_search import DDGS

from handlers.research.searxng import search_searxng


async def _ddg_text(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    def _run() -> List[Dict[str, Any]]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        return []


def _normalize_ddg(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("href") or r.get("url") or r.get("link") or "").strip()
        if not url:
            continue
        out.append(
            {
                "title": (r.get("title") or "").strip() or "Web result",
                "url": url,
                "description": (r.get("body") or r.get("snippet") or "").strip(),
                "source": "ddg",
                "provider": "ddg",
            }
        )
    return out


async def search_general(query: str, min_results: int = 3) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    out: List[Dict[str, Any]] = []
    searx_failed = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sx = await search_searxng(client, q, max_results=8, category="general", source_name="searxng", domain="general")
        for r in sx:
            rr = dict(r)
            rr["provider"] = "searxng"
            out.append(rr)
    except Exception:
        searx_failed = True

    if searx_failed or len(out) < int(min_results):
        ddg_rows = _normalize_ddg(await _ddg_text(q, max_results=10))
        seen = {str(r.get("url")) for r in out if isinstance(r, dict)}
        for r in ddg_rows:
            if str(r.get("url")) in seen:
                continue
            out.append(r)

    return out
