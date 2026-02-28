from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict


def _content(payload: Dict[str, Any]) -> Dict[str, Any]:
    c = dict(payload.get("content") or payload.get("data") or {})
    payload["content"] = c
    payload.setdefault("data", c)
    return c


def _ensure_extra_sections(content: Dict[str, Any]) -> None:
    sections = content.get("extra_sections")
    if not isinstance(sections, list):
        content["extra_sections"] = []
        return
    clean = []
    for s in sections:
        if isinstance(s, dict):
            title = str(s.get("title") or "").strip()[:120]
            body = str(s.get("content") or "").strip()[:2000]
            if title and body:
                clean.append({"title": title, "content": body})
    content["extra_sections"] = clean[:12]


def _render_extra_sections(content: Dict[str, Any]) -> str:
    return "\n\n".join(f"## {s['title']}\n{s['content']}" for s in content.get("extra_sections", []))


def _ensure_list_of_str(content: Dict[str, Any], key: str, *, max_len: int, item_max: int = 240) -> None:
    items = content.get(key)
    if not isinstance(items, list):
        content[key] = []
        return
    content[key] = [str(x).strip()[:item_max] for x in items if str(x).strip()][:max_len]


def _require_known_fields(content: Dict[str, Any], allowed: set[str]) -> None:
    unknown = [k for k in content.keys() if k not in allowed]
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")


def validate_research_brief_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"summary", "key_findings", "consensus", "open_questions", "extra_sections"})
    c.setdefault("summary", "")
    _ensure_list_of_str(c, "key_findings", max_len=12)
    c.setdefault("consensus", "")
    _ensure_list_of_str(c, "open_questions", max_len=12)
    _ensure_extra_sections(c)
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_research_brief_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_research_brief_lenient(payload)
    c = p["content"]
    if not c.get("summary") or not c.get("key_findings"):
        raise ValueError("research_brief.summary and key_findings required")
    return p


def research_brief_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_research_brief_lenient(payload)["content"]
    lines = ["# Research Brief", "", "## Summary", c.get("summary", ""), "", "## Key Findings"]
    lines += [f"- {item}" for item in c.get("key_findings", [])]
    if c.get("consensus"):
        lines += ["", "## Consensus", c["consensus"]]
    if c.get("open_questions"):
        lines += ["", "## Open Questions"] + [f"- {q}" for q in c["open_questions"]]
    extra = _render_extra_sections(c)
    if extra:
        lines += ["", extra]
    return "\n".join(lines).strip()


def validate_doc_extract_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"document_summary", "extracted_points", "table_extract", "page_refs", "extra_sections"})
    c.setdefault("document_summary", "")
    _ensure_list_of_str(c, "extracted_points", max_len=20)
    _ensure_list_of_str(c, "table_extract", max_len=20)
    _ensure_list_of_str(c, "page_refs", max_len=20)
    _ensure_extra_sections(c)
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_doc_extract_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_doc_extract_lenient(payload)
    c = p["content"]
    if not c.get("document_summary") or not c.get("extracted_points"):
        raise ValueError("doc_extract.document_summary and extracted_points required")
    return p


def doc_extract_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_doc_extract_lenient(payload)["content"]
    lines = ["# Document Extract", "", "## Summary", c.get("document_summary", ""), "", "## Extracted Points"]
    lines += [f"- {pt}" for pt in c.get("extracted_points", [])]
    if c.get("page_refs"):
        lines += ["", "## Page References"] + [f"- {ref}" for ref in c["page_refs"]]
    return "\n".join(lines).strip()


def validate_plan_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"objective", "steps", "constraints", "risks", "extra_sections"})
    c["objective"] = str(c.get("objective") or "")[:500]
    _ensure_list_of_str(c, "steps", max_len=12)
    _ensure_list_of_str(c, "constraints", max_len=12)
    _ensure_list_of_str(c, "risks", max_len=10)
    _ensure_extra_sections(c)
    return p


def validate_plan_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_plan_lenient(payload)
    c = p["content"]
    if not c.get("objective") or not c.get("steps"):
        raise ValueError("plan objective and steps required")
    return p


def plan_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_plan_lenient(payload)["content"]
    lines = ["# Plan", "", "## Objective", c.get("objective", ""), "", "## Steps"]
    lines += [f"{idx}. {step}" for idx, step in enumerate(c.get("steps", []), 1)]
    return "\n".join(lines).strip()


def validate_meeting_summary_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"title", "date", "attendees", "summary", "decisions", "action_items", "risks_blockers", "extra_sections"})
    c["title"] = str(c.get("title") or "Meeting Summary")[:200]
    c["date"] = c.get("date")
    _ensure_list_of_str(c, "attendees", max_len=30)
    _ensure_list_of_str(c, "summary", max_len=12)
    _ensure_list_of_str(c, "decisions", max_len=10)
    _ensure_list_of_str(c, "risks_blockers", max_len=8)
    clean = []
    for row in list(c.get("action_items") or [])[:25]:
        if isinstance(row, dict):
            task = str(row.get("task") or "").strip()[:240]
            if task:
                clean.append({"owner": str(row.get("owner") or "Unassigned")[:80], "task": task, "due": row.get("due")})
    c["action_items"] = clean
    _ensure_extra_sections(c)
    return p


def validate_meeting_summary_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_meeting_summary_lenient(payload)
    c = p["content"]
    if not c.get("summary"):
        raise ValueError("meeting_summary.summary required")
    return p


def meeting_summary_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_meeting_summary_lenient(payload)["content"]
    lines = ["# Meeting Summary", "", f"## Title\n{c.get('title', 'Meeting Summary')}", "", "## Summary"]
    lines += [f"- {x}" for x in c.get("summary", [])]
    lines += ["", "## Action Items", "", "| Owner | Task | Due |", "|---|---|---|"]
    lines += [f"| {r.get('owner','Unassigned')} | {r.get('task','')} | {r.get('due') or ''} |" for r in c.get("action_items", [])]
    return "\n".join(lines).strip()


def validate_decision_matrix_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"question", "options", "criteria", "scores", "totals", "recommendation", "sensitivity_notes", "extra_sections"})
    c["question"] = str(c.get("question") or "")[:300]
    _ensure_list_of_str(c, "options", max_len=8)
    criteria = []
    for cr in list(c.get("criteria") or [])[:8]:
        if isinstance(cr, dict) and str(cr.get("name") or "").strip():
            criteria.append({"name": str(cr.get("name")).strip()[:120], "weight": max(0.0, float(cr.get("weight") or 0.0)), "rationale": str(cr.get("rationale") or "")[:240]})
    c["criteria"] = criteria
    scores = []
    for row in list(c.get("scores") or []):
        if isinstance(row, dict):
            try:
                scores.append({"option": str(row.get("option") or "").strip(), "criterion": str(row.get("criterion") or "").strip(), "score": int(row.get("score")), "justification": str(row.get("justification") or "")[:240]})
            except Exception:
                continue
    c["scores"] = scores
    c["totals"] = [t for t in list(c.get("totals") or []) if isinstance(t, dict)][:8]
    c["recommendation"] = str(c.get("recommendation") or "")[:500]
    _ensure_list_of_str(c, "sensitivity_notes", max_len=10)
    _ensure_extra_sections(c)
    return p


def validate_decision_matrix_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_decision_matrix_lenient(payload)
    c = p["content"]
    options = list(c.get("options") or [])
    criteria = list(c.get("criteria") or [])
    scores = list(c.get("scores") or [])
    if len(options) < 2 or len(options) > 8:
        raise ValueError("decision_matrix.options 2-8 required")
    if len(criteria) < 2:
        raise ValueError("decision_matrix.criteria min 2 required")
    weight_sum = sum(float(x.get("weight") or 0.0) for x in criteria)
    if not (0.999 <= weight_sum <= 1.001):
        raise ValueError("decision_matrix.criteria weights must normalize to 1.0")
    expected = {(o, c2.get("name")) for o in options for c2 in criteria}
    covered = {(s.get("option"), s.get("criterion")) for s in scores}
    if covered != expected:
        raise ValueError("decision_matrix.scores must cover full option×criterion matrix")
    if any(not (1 <= int(s.get("score")) <= 5) for s in scores):
        raise ValueError("decision_matrix.score must be 1-5")
    if len(list(c.get("totals") or [])) != len(options):
        raise ValueError("decision_matrix.totals required for each option")
    if not c.get("recommendation"):
        raise ValueError("decision_matrix.recommendation required")
    return p


def decision_matrix_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_decision_matrix_lenient(payload)["content"]
    lines = ["# Decision Matrix", "", "## Question", c.get("question", ""), "", "## Options"] + [f"- {o}" for o in c.get("options", [])]
    return "\n".join(lines).strip()


def validate_action_items_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"title", "items", "extra_sections"})
    c["title"] = str(c.get("title") or "Action Items")[:200]
    items = []
    for item in list(c.get("items") or [])[:25]:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task") or "").strip()[:240]
        if not task:
            continue
        pr = item.get("priority")
        if pr not in {None, "low", "med", "high"}:
            pr = None
        items.append({"owner": str(item.get("owner") or "Unassigned")[:80], "task": task, "due": item.get("due"), "priority": pr})
    c["items"] = items
    _ensure_extra_sections(c)
    return p


def validate_action_items_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_action_items_lenient(payload)
    for item in p["content"]["items"]:
        if not item.get("task"):
            raise ValueError("action_items.item.task required")
    return p


def action_items_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_action_items_lenient(payload)["content"]
    grouped = defaultdict(list)
    for row in c.get("items", []):
        grouped[row.get("owner") or "Unassigned"].append(row)
    lines = ["# Action Items"]
    for owner in sorted(grouped):
        lines += ["", f"## {owner}"]
        lines += [f"- {r['task']}" + (f" (due: {r['due']})" if r.get("due") else "") for r in grouped[owner]]
    return "\n".join(lines).strip()


def validate_status_update_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"period", "done", "doing", "blocked", "asks", "next", "risks", "extra_sections"})
    c["period"] = c.get("period")
    _ensure_list_of_str(c, "done", max_len=12)
    _ensure_list_of_str(c, "doing", max_len=12)
    _ensure_list_of_str(c, "blocked", max_len=12)
    _ensure_list_of_str(c, "next", max_len=12)
    _ensure_list_of_str(c, "asks", max_len=8)
    _ensure_list_of_str(c, "risks", max_len=8)
    _ensure_extra_sections(c)
    return p


def validate_status_update_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    return validate_status_update_lenient(payload)


def status_update_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_status_update_lenient(payload)["content"]
    lines = ["# Status Update"]
    for sec in ["done", "doing", "blocked", "asks", "next", "risks"]:
        vals = c.get(sec) or []
        if vals:
            lines += ["", f"## {sec.title()}"] + [f"- {v}" for v in vals]
    return "\n".join(lines).strip()


STRICT_VALIDATORS = {
    "research_brief": validate_research_brief_strict,
    "doc_extract": validate_doc_extract_strict,
    "plan": validate_plan_strict,
    "meeting_summary": validate_meeting_summary_strict,
    "decision_matrix": validate_decision_matrix_strict,
    "action_items": validate_action_items_strict,
    "status_update": validate_status_update_strict,
}

MARKDOWN_RENDERERS = {
    "research_brief": research_brief_to_markdown,
    "doc_extract": doc_extract_to_markdown,
    "plan": plan_to_markdown,
    "meeting_summary": meeting_summary_to_markdown,
    "decision_matrix": decision_matrix_to_markdown,
    "action_items": action_items_to_markdown,
    "status_update": status_update_to_markdown,
}


def validate_artifact(contract_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    validator = STRICT_VALIDATORS.get(str(contract_name or ""))
    if not validator:
        raise ValueError(f"No validator for contract={contract_name}")
    return validator(payload)
