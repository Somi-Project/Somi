from __future__ import annotations

from typing import Any, Dict

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import SearchEnvelope


def build_research_brief(*, query: str, route: str, envelope: SearchEnvelope, min_sources: int = 3) -> Dict[str, Any]:
    sources = envelope.sources or []
    findings = []
    citations = []
    for s in sources[:8]:
        title = str(s.get("title") or "").strip()
        snippet = str(s.get("snippet") or "").strip()
        url = str(s.get("url") or "").strip()
        if snippet:
            findings.append(snippet)
        elif title:
            findings.append(title)
        if url:
            citations.append({"type": "web", "url": url, "title": title})

    if len(sources) < int(min_sources):
        findings.append("Limited source coverage; confidence reduced.")

    content = {
        "summary": envelope.answer_text[:1200] if envelope.answer_text else "Research summary generated from available sources.",
        "key_findings": findings[:6] or ["No robust findings available."],
        "consensus": "Consensus appears mixed unless corroborated across multiple sources.",
        "open_questions": [],
        "extra_sections": [],
    }
    return build_base(
        artifact_type="research_brief",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=citations,
        confidence=0.86 if len(sources) >= int(min_sources) else 0.62,
        metadata={"source_count": len(sources)},
    )
