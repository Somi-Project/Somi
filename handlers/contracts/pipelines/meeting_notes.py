from __future__ import annotations

import re
from typing import Any, Dict, List

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import DocEnvelope, LLMEnvelope


def _extract_section_block(text: str, header: str) -> str:
    patt = rf"(?is)(?:^|\n)\s*{re.escape(header)}\s*(.*?)(?=\n\s*[A-Za-z][A-Za-z ]{{1,30}}:\s*|\Z)"
    m = re.search(patt, text)
    return (m.group(1) if m else "").strip()


def _bullets(block: str, *, max_items: int) -> List[str]:
    if not block:
        return []
    out = []
    for ln in block.splitlines():
        t = ln.strip(" -•\t")
        if t:
            out.append(t)
    if not out and block:
        for part in re.split(r"[.;]\s+", block):
            t = part.strip()
            if t:
                out.append(t)
    return out[:max_items]


def _parse_action_items(text: str) -> List[Dict[str, Any]]:
    block = _extract_section_block(text, "Action items:")
    if not block:
        return []
    items = []
    for ln in block.splitlines():
        t = ln.strip(" -•\t")
        if not t:
            continue
        owner = "Unassigned"
        due = None
        task = t
        owner_match = re.match(r"^([A-Za-z][A-Za-z .'-]{1,30})\s*[-:]\s*(.+)$", t)
        if owner_match:
            owner = owner_match.group(1).strip()
            task = owner_match.group(2).strip()
        due_match = re.search(r"\b(due|by)\s+([^,;]+)$", task, flags=re.IGNORECASE)
        if due_match:
            due = due_match.group(2).strip()
            task = re.sub(r"\b(due|by)\s+([^,;]+)$", "", task, flags=re.IGNORECASE).strip(" ,.-")
        items.append({"owner": owner or "Unassigned", "task": task or t, "due": due})
    return items[:16]


def _extract_date(text: str) -> str | None:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z][a-z]{2,8}\s+\d{1,2},\s*\d{4})\b", text)
    return m.group(1) if m else None


def _title_from_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "Meeting Summary"
    return q[:80]


def _extra_sections_from_query(query: str, text: str) -> List[Dict[str, str]]:
    q = (query or "").lower()
    out: List[Dict[str, str]] = []
    for key, title in [("next steps", "Next Steps"), ("risks", "Risks"), ("timeline", "Timeline")]:
        if key in q:
            body = _extract_section_block(text, f"{title}:")
            body = body or f"No explicit {title.lower()} provided in notes."
            out.append({"title": title, "content": body})
    return out


def build_meeting_summary(*, query: str, route: str, envelope: LLMEnvelope, doc_envelope: DocEnvelope | None = None) -> Dict[str, Any]:
    source_text = "\n".join([
        (doc_envelope.answer_text if doc_envelope else "") or "",
        "\n".join((doc_envelope.chunks if doc_envelope else []) or []),
        envelope.answer_text or "",
        query or "",
    ]).strip()

    summary = _bullets(_extract_section_block(source_text, "Summary:"), max_items=12)
    if not summary:
        summary = _bullets(source_text, max_items=6)

    decisions = _bullets(_extract_section_block(source_text, "Decisions:"), max_items=10)
    open_action_items = _parse_action_items(source_text)
    attendees = _bullets(_extract_section_block(source_text, "Attendees:"), max_items=24)
    risks_blockers = _bullets(_extract_section_block(source_text, "Risks/Blockers:"), max_items=8)
    if not risks_blockers:
        risks_blockers = _bullets(_extract_section_block(source_text, "Risks:"), max_items=8)

    content = {
        "title": _title_from_query(query),
        "date": _extract_date(source_text),
        "attendees": attendees,
        "summary": summary[:12],
        "decisions": decisions[:10],
        "action_items": open_action_items,
        "risks_blockers": risks_blockers[:8],
        "extra_sections": _extra_sections_from_query(query, source_text),
    }

    return build_base(
        artifact_type="meeting_summary",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=[],
        confidence=0.8,
        metadata={"derived_from": "meeting_notes"},
    )
