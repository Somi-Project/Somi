from __future__ import annotations

from typing import Any, Dict

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import DocEnvelope


def build_doc_extract(*, query: str, route: str, envelope: DocEnvelope) -> Dict[str, Any]:
    extracted = [c for c in (envelope.chunks or []) if c][:8]
    content = {
        "document_summary": envelope.answer_text[:1200] if envelope.answer_text else "Document extraction summary.",
        "extracted_points": extracted or ["No extractable chunks found."],
        "table_extract": [],
        "page_refs": list(envelope.page_refs or []),
        "extra_sections": [],
    }
    citations = [{"type": "doc", "ref": p} for p in envelope.page_refs or []]
    return build_base(
        artifact_type="doc_extract",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=citations,
        confidence=0.78 if extracted else 0.55,
        metadata={"chunk_count": len(extracted)},
    )
