from __future__ import annotations

import asyncio
import re
from typing import Iterable

import httpx

from handlers.research.evidence_schema import EvidenceItem

_META_DATE_RE = re.compile(r'<meta[^>]+(?:property|name)="(?:article:published_time|pubdate|date)"[^>]+content="([^"]+)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _extract_excerpt(html: str, max_chars: int = 2500) -> str:
    text = _TAG_RE.sub(" ", html or "")
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def _extract_date(html: str) -> str | None:
    m = _META_DATE_RE.search(html or "")
    if not m:
        return None
    return (m.group(1) or "").strip() or None


async def deep_read_items(items: Iterable[EvidenceItem], *, max_reads: int = 8, timeout_s: float = 10.0) -> list[EvidenceItem]:
    all_items = list(items)
    targets = all_items[: max(0, int(max_reads))]

    async def _read_one(client: httpx.AsyncClient, item: EvidenceItem) -> EvidenceItem:
        try:
            r = await client.get(item.url, follow_redirects=True)
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/html" not in ctype:
                item.score = max(0.0, item.score - 0.08)
                return item
            body = r.text or ""
            item.content_excerpt = _extract_excerpt(body)
            if not item.published_date:
                item.published_date = _extract_date(body)
            return item
        except Exception:
            item.score = max(0.0, item.score - 0.1)
            return item

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        read = await asyncio.gather(*[_read_one(client, it) for it in targets])
    by_id = {i.id: i for i in read}
    return [by_id.get(i.id, i) for i in all_items]
