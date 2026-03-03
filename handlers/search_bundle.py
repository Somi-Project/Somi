from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source_domain: str
    published_date: Optional[str] = None


@dataclass
class SearchBundle:
    query: str
    results: List[SearchResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def strip_tracking_params(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def render_search_bundle(bundle: SearchBundle, max_results: int = 5, max_snippet_chars: int = 320) -> str:
    lines = [f"EVIDENCE (top N={max_results}):"]
    for idx, item in enumerate(bundle.results[:max_results], start=1):
        snippet = (item.snippet or "").strip()
        if len(snippet) > max_snippet_chars:
            snippet = snippet[: max_snippet_chars - 3].rstrip() + "..."
        lines.extend(
            [
                f"{idx}) {item.title}",
                f"   {item.url}",
                f"   {item.published_date or 'date: unknown'}",
                f"   {snippet}",
            ]
        )

    warn = "; ".join(bundle.warnings) if bundle.warnings else "none"
    lines.append(f"WARNINGS: {warn}")
    return "\n".join(lines)
