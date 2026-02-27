from __future__ import annotations

from typing import Any, Dict, List


def _ensure_extra_sections(content: Dict[str, Any]) -> None:
    sections = content.get("extra_sections")
    if not isinstance(sections, list):
        content["extra_sections"] = []
        return
    clean = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        body = str(s.get("content") or "").strip()
        if title and body:
            clean.append({"title": title, "content": body})
    content["extra_sections"] = clean


def _render_extra_sections(content: Dict[str, Any]) -> str:
    out = []
    for sec in content.get("extra_sections", []):
        out.append(f"## {sec['title']}\n{sec['content']}")
    return "\n\n".join(out)


def validate_research_brief_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = dict(p.get("content") or {})
    c.setdefault("summary", "")
    c.setdefault("key_findings", [])
    c.setdefault("consensus", "")
    c.setdefault("open_questions", [])
    _ensure_extra_sections(c)
    p["content"] = c
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_research_brief_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_research_brief_lenient(payload)
    c = p["content"]
    if not c.get("summary"):
        raise ValueError("research_brief.summary required")
    if not isinstance(c.get("key_findings"), list) or not c["key_findings"]:
        raise ValueError("research_brief.key_findings required")
    return p


def research_brief_to_markdown(payload: Dict[str, Any]) -> str:
    p = validate_research_brief_lenient(payload)
    c = p["content"]
    lines = [
        "# Research Brief",
        "",
        "## Summary",
        c.get("summary", ""),
        "",
        "## Key Findings",
    ]
    for item in c.get("key_findings", []):
        lines.append(f"- {item}")
    if c.get("consensus"):
        lines.extend(["", "## Consensus", c["consensus"]])
    if c.get("open_questions"):
        lines.extend(["", "## Open Questions"])
        for q in c["open_questions"]:
            lines.append(f"- {q}")
    extra = _render_extra_sections(c)
    if extra:
        lines.extend(["", extra])
    return "\n".join(lines).strip()


def validate_doc_extract_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = dict(p.get("content") or {})
    c.setdefault("document_summary", "")
    c.setdefault("extracted_points", [])
    c.setdefault("table_extract", [])
    c.setdefault("page_refs", [])
    _ensure_extra_sections(c)
    p["content"] = c
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_doc_extract_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_doc_extract_lenient(payload)
    c = p["content"]
    if not c.get("document_summary"):
        raise ValueError("doc_extract.document_summary required")
    if not isinstance(c.get("extracted_points"), list) or not c["extracted_points"]:
        raise ValueError("doc_extract.extracted_points required")
    return p


def doc_extract_to_markdown(payload: Dict[str, Any]) -> str:
    p = validate_doc_extract_lenient(payload)
    c = p["content"]
    lines = ["# Document Extract", "", "## Summary", c.get("document_summary", ""), "", "## Extracted Points"]
    for pt in c.get("extracted_points", []):
        lines.append(f"- {pt}")
    if c.get("table_extract"):
        lines.extend(["", "## Table Extract"])
        for row in c["table_extract"]:
            lines.append(f"- {row}")
    if c.get("page_refs"):
        lines.extend(["", "## Page References"])
        for ref in c["page_refs"]:
            lines.append(f"- {ref}")
    extra = _render_extra_sections(c)
    if extra:
        lines.extend(["", extra])
    return "\n".join(lines).strip()


def validate_plan_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = dict(p.get("content") or {})
    c.setdefault("objective", "")
    c.setdefault("steps", [])
    c.setdefault("constraints", [])
    c.setdefault("risks", [])
    _ensure_extra_sections(c)
    p["content"] = c
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_plan_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_plan_lenient(payload)
    c = p["content"]
    if not c.get("objective"):
        raise ValueError("plan.objective required")
    if not isinstance(c.get("steps"), list) or not c["steps"]:
        raise ValueError("plan.steps required")
    return p


def plan_to_markdown(payload: Dict[str, Any]) -> str:
    p = validate_plan_lenient(payload)
    c = p["content"]
    lines = ["# Plan", "", "## Objective", c.get("objective", ""), "", "## Steps"]
    for idx, step in enumerate(c.get("steps", []), start=1):
        lines.append(f"{idx}. {step}")
    if c.get("constraints"):
        lines.extend(["", "## Constraints"])
        for item in c["constraints"]:
            lines.append(f"- {item}")
    if c.get("risks"):
        lines.extend(["", "## Risks"])
        for item in c["risks"]:
            lines.append(f"- {item}")
    extra = _render_extra_sections(c)
    if extra:
        lines.extend(["", extra])
    return "\n".join(lines).strip()


STRICT_VALIDATORS = {
    "research_brief": validate_research_brief_strict,
    "doc_extract": validate_doc_extract_strict,
    "plan": validate_plan_strict,
}

MARKDOWN_RENDERERS = {
    "research_brief": research_brief_to_markdown,
    "doc_extract": doc_extract_to_markdown,
    "plan": plan_to_markdown,
}
