from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
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
    summary: str = ""
    execution_trace: List[str] = field(default_factory=list)
    research_brief: Dict[str, object] = field(default_factory=dict)
    section_bundles: List[Dict[str, object]] = field(default_factory=list)


def strip_tracking_params(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def render_search_bundle(bundle: SearchBundle, max_results: int = 6, max_snippet_chars: int = 350) -> str:
    lines = []
    brief = dict(bundle.research_brief or {}) if isinstance(bundle.research_brief, dict) else {}
    if brief:
        objective = str(brief.get("objective") or "").strip()
        if objective:
            lines.extend(["RESEARCH BRIEF:", objective, ""])
    sections = list(bundle.section_bundles or [])
    if sections:
        labels = [str(section.get("title") or "").strip() for section in sections[:4] if isinstance(section, dict)]
        labels = [label for label in labels if label]
        if labels:
            lines.extend(["SECTION PLAN:", ", ".join(labels), ""])
    if (bundle.summary or "").strip():
        lines.extend(["EVIDENCE SUMMARY:", (bundle.summary or "").strip(), ""])
    if list(bundle.execution_trace or []):
        lines.append("EXECUTION TRACE:")
        for item in list(bundle.execution_trace or [])[:6]:
            clean = " ".join(str(item or "").split()).strip()
            if clean:
                lines.append(f"- {clean}")
        lines.append("")
    lines.append(f"EVIDENCE (top N={max_results}):")
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

