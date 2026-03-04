from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class SearchProfile:
    name: str
    category: str = "general"
    engines: List[str] = field(default_factory=list)
    time_range: str | None = None
    language: str | None = None
    safe: int | str | None = None
    domain: str = "general"


def normalize_search_result(
    row: Dict[str, Any],
    *,
    source: str,
    provider: str,
    fallback_title: str = "Web result",
) -> Dict[str, Any]:
    r = dict(row or {}) if isinstance(row, dict) else {}
    title = str(r.get("title") or fallback_title).strip() or fallback_title
    url = str(r.get("url") or r.get("href") or r.get("link") or "").strip()
    description = str(r.get("description") or r.get("body") or r.get("snippet") or r.get("content") or "").strip()
    out = dict(r)
    out["title"] = title
    out["url"] = url
    out["description"] = description
    out["source"] = str(r.get("source") or source)
    out["provider"] = str(r.get("provider") or provider)
    return out


def dedupe_by_url(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        u = str(row.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(row)
    return out
