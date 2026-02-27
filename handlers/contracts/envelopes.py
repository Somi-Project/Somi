from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SearchEnvelope:
    answer_text: str
    sources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DocEnvelope:
    answer_text: str
    chunks: List[str] = field(default_factory=list)
    page_refs: List[str] = field(default_factory=list)


@dataclass
class LLMEnvelope:
    answer_text: str


def to_search_envelope(answer_text: str, raw_results: list[dict] | None) -> SearchEnvelope:
    sources = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "").strip()
        title = str(r.get("title") or "").strip()
        snippet = str(r.get("description") or "").strip()
        if url or title:
            sources.append({"url": url, "title": title, "snippet": snippet})
    return SearchEnvelope(answer_text=answer_text or "", sources=sources)


def to_doc_envelope(answer_text: str, rag_block: str | None) -> DocEnvelope:
    chunks = []
    if rag_block:
        # lightweight line-based split for now
        for ln in str(rag_block).splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("##"):
                chunks.append(ln)
    return DocEnvelope(answer_text=answer_text or "", chunks=chunks, page_refs=[])


def to_llm_envelope(answer_text: str) -> LLMEnvelope:
    return LLMEnvelope(answer_text=answer_text or "")
