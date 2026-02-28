from __future__ import annotations

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


def _ensure_list_of_str(content: Dict[str, Any], key: str, *, max_len: int | None = None) -> None:
    items = content.get(key)
    if not isinstance(items, list):
        content[key] = []
        return
    clean = [str(x).strip() for x in items if str(x).strip()]
    if max_len is not None:
        clean = clean[:max_len]
    content[key] = clean


def validate_research_brief_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    c.setdefault("summary", "")
    c.setdefault("key_findings", [])
    c.setdefault("consensus", "")
    c.setdefault("open_questions", [])
    _ensure_extra_sections(c)
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
    lines = ["# Research Brief", "", "## Summary", c.get("summary", ""), "", "## Key Findings"]
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
    c = _content(p)
    c.setdefault("document_summary", "")
    c.setdefault("extracted_points", [])
    c.setdefault("table_extract", [])
    c.setdefault("page_refs", [])
    _ensure_extra_sections(c)
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
    c = _content(p)
    c.setdefault("objective", "")
    c.setdefault("steps", [])
    c.setdefault("constraints", [])
    c.setdefault("risks", [])
    _ensure_extra_sections(c)
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


def validate_meeting_summary_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    c.setdefault("title", "Meeting Summary")
    c.setdefault("date", None)
    _ensure_list_of_str(c, "attendees")
    _ensure_list_of_str(c, "summary", max_len=12)
    _ensure_list_of_str(c, "decisions", max_len=10)
    _ensure_list_of_str(c, "risks_blockers", max_len=8)

    action_items = c.get("action_items")
    if not isinstance(action_items, list):
        action_items = []
    clean_actions = []
    for item in action_items:
        if isinstance(item, dict):
            owner = str(item.get("owner") or "Unassigned").strip() or "Unassigned"
            task = str(item.get("task") or "").strip()
            due_raw = item.get("due")
            due = str(due_raw).strip() if due_raw is not None and str(due_raw).strip() else None
            if task:
                clean_actions.append({"owner": owner, "task": task, "due": due})
        else:
            task = str(item).strip()
            if task:
                clean_actions.append({"owner": "Unassigned", "task": task, "due": None})
    c["action_items"] = clean_actions[:16]
    _ensure_extra_sections(c)
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_meeting_summary_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_meeting_summary_lenient(payload)
    c = p["content"]
    if not str(c.get("title") or "").strip():
        raise ValueError("meeting_summary.title required")
    if not isinstance(c.get("summary"), list):
        raise ValueError("meeting_summary.summary required")
    if not isinstance(c.get("decisions"), list):
        raise ValueError("meeting_summary.decisions required")
    if not isinstance(c.get("action_items"), list):
        raise ValueError("meeting_summary.action_items required")
    if not isinstance(c.get("risks_blockers"), list):
        raise ValueError("meeting_summary.risks_blockers required")
    if len(c.get("summary") or []) > 12:
        raise ValueError("meeting_summary.summary max 12")
    if len(c.get("decisions") or []) > 10:
        raise ValueError("meeting_summary.decisions max 10")
    if len(c.get("risks_blockers") or []) > 8:
        raise ValueError("meeting_summary.risks_blockers max 8")
    return p


def meeting_summary_to_markdown(payload: Dict[str, Any]) -> str:
    p = validate_meeting_summary_lenient(payload)
    c = p["content"]
    lines = ["# Meeting Summary", "", f"## Title\n{c.get('title', 'Meeting Summary')}"]
    if c.get("date"):
        lines.extend(["", f"**Date:** {c['date']}"])
    if c.get("attendees"):
        lines.extend(["", "## Attendees"])
        for x in c["attendees"]:
            lines.append(f"- {x}")
    lines.extend(["", "## Summary"])
    for x in c.get("summary", []):
        lines.append(f"- {x}")
    lines.extend(["", "## Decisions"])
    for x in c.get("decisions", []):
        lines.append(f"- {x}")

    lines.extend(["", "## Action Items", "", "| Owner | Task | Due |", "|---|---|---|"])
    for row in c.get("action_items", []):
        lines.append(f"| {row.get('owner', 'Unassigned')} | {row.get('task', '')} | {row.get('due') or ''} |")

    if c.get("risks_blockers"):
        lines.extend(["", "## Risks / Blockers"])
        for x in c["risks_blockers"]:
            lines.append(f"- {x}")

    extra = _render_extra_sections(c)
    if extra:
        lines.extend(["", extra])
    return "\n".join(lines).strip()


def validate_decision_matrix_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    c.setdefault("question", "")
    _ensure_list_of_str(c, "options", max_len=8)

    criteria = c.get("criteria")
    if not isinstance(criteria, list):
        criteria = []
    cleaned_criteria = []
    for cr in criteria:
        if not isinstance(cr, dict):
            continue
        name = str(cr.get("name") or "").strip()
        if not name:
            continue
        try:
            weight = float(cr.get("weight") or 0.0)
        except Exception:
            weight = 0.0
        cleaned_criteria.append({"name": name, "weight": max(0.0, weight), "rationale": str(cr.get("rationale") or "").strip()})
    c["criteria"] = cleaned_criteria[:7]

    scores = c.get("scores")
    if not isinstance(scores, list):
        scores = []
    clean_scores = []
    for row in scores:
        if not isinstance(row, dict):
            continue
        option = str(row.get("option") or "").strip()
        criterion = str(row.get("criterion") or "").strip()
        try:
            score = int(row.get("score"))
        except Exception:
            continue
        justification = str(row.get("justification") or "").strip()
        if option and criterion:
            clean_scores.append({"option": option, "criterion": criterion, "score": score, "justification": justification})
    c["scores"] = clean_scores

    totals = c.get("totals")
    if not isinstance(totals, list):
        totals = []
    clean_totals = []
    for t in totals:
        if not isinstance(t, dict):
            continue
        option = str(t.get("option") or "").strip()
        try:
            wt = float(t.get("weighted_total"))
        except Exception:
            continue
        if option:
            clean_totals.append({"option": option, "weighted_total": wt})
    c["totals"] = clean_totals

    c.setdefault("recommendation", "")
    _ensure_list_of_str(c, "sensitivity_notes", max_len=10)
    _ensure_extra_sections(c)
    p["citations"] = list(p.get("citations") or [])
    return p


def validate_decision_matrix_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_decision_matrix_lenient(payload)
    c = p["content"]
    if not str(c.get("question") or "").strip():
        raise ValueError("decision_matrix.question required")
    options = list(c.get("options") or [])
    criteria = list(c.get("criteria") or [])
    scores = list(c.get("scores") or [])
    totals = list(c.get("totals") or [])

    if len(options) < 2 or len(options) > 8:
        raise ValueError("decision_matrix.options 2-8 required")
    if len(criteria) < 2:
        raise ValueError("decision_matrix.criteria min 2 required")

    weight_sum = sum(float(x.get("weight") or 0.0) for x in criteria)
    if not (0.999 <= weight_sum <= 1.001):
        raise ValueError("decision_matrix.criteria weights must normalize to 1.0")

    covered = {(s.get("option"), s.get("criterion")) for s in scores}
    expected = {(o, c.get("name")) for o in options for c in criteria}
    if covered != expected:
        raise ValueError("decision_matrix.scores must cover full option×criterion matrix")
    for s in scores:
        if not (1 <= int(s.get("score")) <= 5):
            raise ValueError("decision_matrix.score must be 1-5")

    if len(totals) != len(options):
        raise ValueError("decision_matrix.totals required for each option")
    if not str(c.get("recommendation") or "").strip():
        raise ValueError("decision_matrix.recommendation required")
    return p


def decision_matrix_to_markdown(payload: Dict[str, Any]) -> str:
    p = validate_decision_matrix_lenient(payload)
    c = p["content"]
    lines = ["# Decision Matrix", "", "## Question", c.get("question", ""), "", "## Options"]
    for o in c.get("options", []):
        lines.append(f"- {o}")

    lines.extend(["", "## Criteria Weights", "", "| Criterion | Weight |", "|---|---:|"])
    for cr in c.get("criteria", []):
        lines.append(f"| {cr.get('name','')} | {float(cr.get('weight') or 0.0):.3f} |")

    lines.extend(["", "## Scores", "", "| Option | Criterion | Score | Justification |", "|---|---|---:|---|"])
    for row in c.get("scores", []):
        lines.append(
            f"| {row.get('option','')} | {row.get('criterion','')} | {int(row.get('score') or 0)} | {row.get('justification','')} |"
        )

    lines.extend(["", "## Totals", "", "| Option | Weighted Total |", "|---|---:|"])
    for row in c.get("totals", []):
        lines.append(f"| {row.get('option','')} | {float(row.get('weighted_total') or 0.0):.3f} |")

    lines.extend(["", "## Recommendation", c.get("recommendation", "")])
    if c.get("sensitivity_notes"):
        lines.extend(["", "## Sensitivity Notes"])
        for x in c["sensitivity_notes"]:
            lines.append(f"- {x}")
    extra = _render_extra_sections(c)
    if extra:
        lines.extend(["", extra])
    return "\n".join(lines).strip()


STRICT_VALIDATORS = {
    "research_brief": validate_research_brief_strict,
    "doc_extract": validate_doc_extract_strict,
    "plan": validate_plan_strict,
    "meeting_summary": validate_meeting_summary_strict,
    "decision_matrix": validate_decision_matrix_strict,
}

MARKDOWN_RENDERERS = {
    "research_brief": research_brief_to_markdown,
    "doc_extract": doc_extract_to_markdown,
    "plan": plan_to_markdown,
    "meeting_summary": meeting_summary_to_markdown,
    "decision_matrix": decision_matrix_to_markdown,
}
