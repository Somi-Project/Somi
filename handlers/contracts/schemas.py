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


def validate_artifact_continuity_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"thread_id", "top_related_artifacts", "current_state_summary", "suggested_next_steps", "assumptions", "questions", "safety"})
    c["thread_id"] = str(c.get("thread_id") or "")[:120]
    rel = []
    for row in list(c.get("top_related_artifacts") or [])[:10]:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("artifact_id") or "").strip()
        if not aid:
            continue
        status = str(row.get("status") or "unknown").strip()
        rel.append({
            "artifact_id": aid,
            "type": str(row.get("type") or "")[:80],
            "title": str(row.get("title") or "")[:200],
            "status": status,
            "updated_at": row.get("updated_at"),
        })
    c["top_related_artifacts"] = rel
    c["current_state_summary"] = str(c.get("current_state_summary") or "")[:500]
    _ensure_list_of_str(c, "suggested_next_steps", max_len=7)
    _ensure_list_of_str(c, "assumptions", max_len=10)
    _ensure_list_of_str(c, "questions", max_len=5)
    safety = c.get("safety") if isinstance(c.get("safety"), dict) else {}
    c["safety"] = {"no_autonomy": True, "no_execution": True}
    return p


def validate_artifact_continuity_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_artifact_continuity_lenient(payload)
    c = p["content"]
    if not c.get("thread_id"):
        raise ValueError("artifact_continuity.thread_id required")
    if not c.get("current_state_summary"):
        raise ValueError("artifact_continuity.current_state_summary required")
    if not c.get("suggested_next_steps"):
        raise ValueError("artifact_continuity.suggested_next_steps required")
    return p


def artifact_continuity_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_artifact_continuity_lenient(payload)["content"]
    lines = ["# Continuity", "", "## Current State", c.get("current_state_summary", ""), "", "## Suggested Next Steps"]
    lines += [f"- {x}" for x in c.get("suggested_next_steps", [])]
    if c.get("assumptions"):
        lines += ["", "## Assumptions"] + [f"- {x}" for x in c["assumptions"]]
    if c.get("questions"):
        lines += ["", "## Questions"] + [f"- {x}" for x in c["questions"]]
    return "\n".join(lines).strip()


def validate_task_state_lenient(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"thread_id", "tasks", "rollups", "suggested_updates"})
    c["thread_id"] = str(c.get("thread_id") or "")[:120]
    tasks = []
    for row in list(c.get("tasks") or [])[:200]:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown").strip()
        if status not in {"open", "in_progress", "done", "blocked", "unknown"}:
            status = "unknown"
        title = str(row.get("title") or "").strip()[:240]
        task_id = str(row.get("task_id") or "").strip()[:64]
        src = str(row.get("source_artifact_id") or "").strip()
        if not (title and task_id and src):
            continue
        item = {
            "task_id": task_id,
            "title": title,
            "status": status,
            "owner": str(row.get("owner") or "Unassigned")[:80],
            "source_artifact_id": src,
        }
        if row.get("due_date"):
            item["due_date"] = str(row.get("due_date"))[:80]
        if row.get("notes"):
            item["notes"] = str(row.get("notes"))[:240]
        tasks.append(item)
    c["tasks"] = tasks
    roll = c.get("rollups") if isinstance(c.get("rollups"), dict) else {}
    c["rollups"] = {
        "open_count": int(roll.get("open_count") or 0),
        "in_progress_count": int(roll.get("in_progress_count") or 0),
        "done_count": int(roll.get("done_count") or 0),
        "blocked_count": int(roll.get("blocked_count") or 0),
    }
    su = []
    for row in list(c.get("suggested_updates") or [])[:100]:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("task_id") or "").strip()
        st = str(row.get("suggested_status") or "unknown").strip()
        if not tid or st not in {"open", "in_progress", "done", "blocked", "unknown"}:
            continue
        su.append({"task_id": tid, "suggested_status": st, "reason": str(row.get("reason") or "")[:240]})
    c["suggested_updates"] = su
    return p


def validate_task_state_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = validate_task_state_lenient(payload)
    c = p["content"]
    if not c.get("thread_id"):
        raise ValueError("task_state.thread_id required")
    if not isinstance(c.get("tasks"), list):
        raise ValueError("task_state.tasks required")
    return p


def task_state_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_task_state_lenient(payload)["content"]
    lines = ["# Task State", "", "## Tasks"]
    for t in c.get("tasks", []):
        lines.append(f"- [{t.get('status')}] {t.get('title')} ({t.get('owner')})")
    return "\n".join(lines).strip()


def validate_proposal_action_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(
        c,
        {
            "type",
            "proposal_id",
            "capability",
            "risk_tier",
            "summary",
            "justification",
            "scope",
            "steps",
            "preconditions",
            "requires_approval",
            "expires_in_s",
            "no_autonomy",
            "related_artifact_ids",
            "ui_hints",
        },
    )
    if c.get("type") != "proposal_action":
        raise ValueError("proposal_action.type required")
    if not str(c.get("proposal_id") or "").strip() or not str(c.get("capability") or "").strip():
        raise ValueError("proposal_action proposal_id/capability required")
    if c.get("risk_tier") not in {"tier0", "tier1", "tier2", "tier3", "tier4"}:
        raise ValueError("proposal_action risk_tier invalid")
    c["requires_approval"] = bool(c.get("requires_approval", True))
    if not c["requires_approval"]:
        raise ValueError("proposal_action.requires_approval must be true")
    if c.get("risk_tier") in {"tier2", "tier3", "tier4"} and not c["requires_approval"]:
        raise ValueError("tier2+ requires approval")
    c["summary"] = str(c.get("summary") or "")[:500]
    _ensure_list_of_str(c, "justification", max_len=10)
    c["scope"] = dict(c.get("scope") or {})
    c["steps"] = [s for s in list(c.get("steps") or []) if isinstance(s, dict)]
    _ensure_list_of_str(c, "preconditions", max_len=12)
    c["expires_in_s"] = max(1, int(c.get("expires_in_s") or 300))
    c["no_autonomy"] = bool(c.get("no_autonomy", True))
    if not c["no_autonomy"]:
        raise ValueError("proposal_action.no_autonomy must be true")
    _ensure_list_of_str(c, "related_artifact_ids", max_len=20)
    c["ui_hints"] = dict(c.get("ui_hints") or {})
    return p


def validate_approval_token_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "token_id", "token_digest", "proposal_id", "capability", "scope", "issued_at", "expires_at", "one_time", "revoked", "no_autonomy"})
    if c.get("type") != "approval_token":
        raise ValueError("approval_token.type required")
    for k in ("token_id", "token_digest", "proposal_id", "capability", "issued_at", "expires_at"):
        if not str(c.get(k) or "").strip():
            raise ValueError(f"approval_token.{k} required")
    c["scope"] = dict(c.get("scope") or {})
    c["one_time"] = bool(c.get("one_time", True))
    c["revoked"] = bool(c.get("revoked", False))
    c["no_autonomy"] = bool(c.get("no_autonomy", True))
    return p


def validate_executed_action_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "proposal_id", "token_digest", "capability", "started_at", "ended_at", "success", "effects", "outputs", "errors", "audit_event_ids", "no_autonomy"})
    if c.get("type") != "executed_action":
        raise ValueError("executed_action.type required")
    for k in ("proposal_id", "token_digest", "capability", "started_at", "ended_at"):
        if not str(c.get(k) or "").strip():
            raise ValueError(f"executed_action.{k} required")
    c["success"] = bool(c.get("success"))
    c["effects"] = dict(c.get("effects") or {})
    c["outputs"] = dict(c.get("outputs") or {})
    c["errors"] = [e for e in list(c.get("errors") or []) if isinstance(e, dict)]
    _ensure_list_of_str(c, "audit_event_ids", max_len=50)
    c["no_autonomy"] = bool(c.get("no_autonomy", True))
    return p


def validate_denied_action_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "proposal_id", "denied_at", "reason", "no_autonomy"})
    if c.get("type") != "denied_action":
        raise ValueError("denied_action.type required")
    if not str(c.get("proposal_id") or "").strip():
        raise ValueError("denied_action.proposal_id required")
    c["reason"] = str(c.get("reason") or "")[:500]
    c["no_autonomy"] = bool(c.get("no_autonomy", True))
    return p


def validate_revoked_token_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "token_digest", "revoked_at", "reason", "no_autonomy"})
    if c.get("type") != "revoked_token":
        raise ValueError("revoked_token.type required")
    if not str(c.get("token_digest") or "").strip():
        raise ValueError("revoked_token.token_digest required")
    c["reason"] = str(c.get("reason") or "")[:500]
    c["no_autonomy"] = bool(c.get("no_autonomy", True))
    return p


def _sanitize_rel_ids(items: Any, max_len: int = 20) -> list[str]:
    out = []
    for x in list(items or [])[:max_len]:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def validate_daily_brief_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "date", "active_persona_key", "highlights", "open_threads", "open_tasks", "suggestions", "risk_notes", "privacy", "guardrails", "no_autonomy"})
    if c.get("type") != "daily_brief":
        raise ValueError("daily_brief.type required")
    if not str(c.get("date") or "").strip():
        raise ValueError("daily_brief.date required")
    c["active_persona_key"] = str(c.get("active_persona_key") or "")[:160]
    _ensure_list_of_str(c, "highlights", max_len=5)
    ots = []
    for row in list(c.get("open_threads") or [])[:7]:
        if not isinstance(row, dict):
            continue
        ots.append({"thread_id": str(row.get("thread_id") or "")[:120], "title": str(row.get("title") or "")[:200], "status": str(row.get("status") or "open")[:20], "last_updated": row.get("last_updated")})
    c["open_threads"] = ots
    tasks = []
    for row in list(c.get("open_tasks") or [])[:10]:
        if not isinstance(row, dict):
            continue
        tasks.append({"task_id": str(row.get("task_id") or "")[:64], "title": str(row.get("title") or "")[:240], "status": str(row.get("status") or "open")[:20], "age_days": int(row.get("age_days") or 0), "source_artifact_id": row.get("source_artifact_id")})
    c["open_tasks"] = tasks
    sugs = []
    for row in list(c.get("suggestions") or [])[:7]:
        if not isinstance(row, dict):
            continue
        sugs.append({"title": str(row.get("title") or "")[:200], "rationale": str(row.get("rationale") or "")[:300], "related_artifact_ids": _sanitize_rel_ids(row.get("related_artifact_ids"), 20), "requires_execution": bool(row.get("requires_execution", False))})
    c["suggestions"] = sugs
    _ensure_list_of_str(c, "risk_notes", max_len=5)
    privacy = c.get("privacy") if isinstance(c.get("privacy"), dict) else {}
    c["privacy"] = {"mode": "strict" if str(privacy.get("mode") or "strict") == "strict" else "standard", "redactions_applied": bool(privacy.get("redactions_applied", False))}
    guardrails = c.get("guardrails") if isinstance(c.get("guardrails"), dict) else {}
    c["guardrails"] = {"no_autonomy": True, "phase5_required_for_execution": bool(guardrails.get("phase5_required_for_execution", True))}
    c["no_autonomy"] = True
    return p


def validate_heartbeat_tick_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "tick_id", "active_persona_key", "sense", "think", "propose", "privacy", "guardrails", "no_autonomy"})
    if c.get("type") != "heartbeat_tick":
        raise ValueError("heartbeat_tick.type required")
    c["tick_id"] = str(c.get("tick_id") or "")[:160]
    c["active_persona_key"] = str(c.get("active_persona_key") or "")[:160]
    sense = c.get("sense") if isinstance(c.get("sense"), dict) else {}
    c["sense"] = {"signals": [str(x)[:180] for x in list(sense.get("signals") or [])[:20]], "anomalies": [str(x)[:180] for x in list(sense.get("anomalies") or [])[:20]]}
    think = c.get("think") if isinstance(c.get("think"), dict) else {}
    c["think"] = {"summary": str(think.get("summary") or "")[:500], "priorities": [str(x)[:200] for x in list(think.get("priorities") or [])[:10]]}
    props = []
    for row in list(c.get("propose") or [])[:7]:
        if not isinstance(row, dict):
            continue
        props.append({"proposal": str(row.get("proposal") or "")[:240], "related_artifact_ids": _sanitize_rel_ids(row.get("related_artifact_ids"), 20), "requires_execution": bool(row.get("requires_execution", False))})
    c["propose"] = props
    privacy = c.get("privacy") if isinstance(c.get("privacy"), dict) else {}
    c["privacy"] = {"mode": "strict" if str(privacy.get("mode") or "strict") == "strict" else "standard", "redactions_applied": bool(privacy.get("redactions_applied", False))}
    guardrails = c.get("guardrails") if isinstance(c.get("guardrails"), dict) else {}
    c["guardrails"] = {"no_autonomy": True, "phase5_required_for_execution": bool(guardrails.get("phase5_required_for_execution", True))}
    c["no_autonomy"] = True
    return p


def validate_reminder_digest_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "active_persona_key", "items", "suggested_next_actions", "privacy", "no_autonomy"})
    if c.get("type") != "reminder_digest":
        raise ValueError("reminder_digest.type required")
    c["active_persona_key"] = str(c.get("active_persona_key") or "")[:160]
    items = []
    for row in list(c.get("items") or [])[:12]:
        if not isinstance(row, dict):
            continue
        items.append({"title": str(row.get("title") or "")[:200], "why_now": str(row.get("why_now") or "")[:240], "status": str(row.get("status") or "open")[:20], "related_artifact_ids": _sanitize_rel_ids(row.get("related_artifact_ids"), 20)})
    c["items"] = items
    _ensure_list_of_str(c, "suggested_next_actions", max_len=7)
    privacy = c.get("privacy") if isinstance(c.get("privacy"), dict) else {}
    c["privacy"] = {"mode": "strict" if str(privacy.get("mode") or "strict") == "strict" else "standard", "redactions_applied": bool(privacy.get("redactions_applied", False))}
    c["no_autonomy"] = True
    return p


def validate_profile_view_strict(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    c = _content(p)
    _require_known_fields(c, {"type", "active_persona_key", "proactivity_level", "focus_domains", "privacy_mode", "brief_first_interaction_of_day", "last_brief_date", "last_heartbeat_at", "no_autonomy"})
    if c.get("type") != "profile_view":
        raise ValueError("profile_view.type required")
    c["active_persona_key"] = str(c.get("active_persona_key") or "")[:160]
    c["proactivity_level"] = int(c.get("proactivity_level") or 1)
    _ensure_list_of_str(c, "focus_domains", max_len=7, item_max=40)
    c["privacy_mode"] = "strict" if str(c.get("privacy_mode") or "strict") == "strict" else "standard"
    c["brief_first_interaction_of_day"] = bool(c.get("brief_first_interaction_of_day", False))
    c["last_brief_date"] = c.get("last_brief_date")
    c["last_heartbeat_at"] = c.get("last_heartbeat_at")
    c["no_autonomy"] = True
    return p


def daily_brief_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_daily_brief_strict(payload)["content"]
    lines = ["# Daily Brief", f"Date: {c.get('date','')}", "", "## Highlights"]
    lines += [f"- {x}" for x in c.get("highlights", [])]
    lines += ["", "## Open Threads"] + [f"- [{r.get('status')}] {r.get('title')}" for r in c.get("open_threads", [])]
    lines += ["", "## Suggestions"] + [f"- {s.get('title')}" for s in c.get("suggestions", [])]
    return "\n".join(lines).strip()


def heartbeat_tick_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_heartbeat_tick_strict(payload)["content"]
    lines = ["# Heartbeat Tick", "", f"## Summary\n{c.get('think', {}).get('summary', '')}", "", "## Proposals"]
    lines += [f"- {p.get('proposal')}" for p in c.get("propose", [])]
    return "\n".join(lines).strip()


def reminder_digest_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_reminder_digest_strict(payload)["content"]
    lines = ["# Reminder Digest", "", "## Items"]
    lines += [f"- [{it.get('status')}] {it.get('title')}: {it.get('why_now')}" for it in c.get("items", [])]
    return "\n".join(lines).strip()


def profile_view_to_markdown(payload: Dict[str, Any]) -> str:
    c = validate_profile_view_strict(payload)["content"]
    return "\n".join([
        "# Assistant Profile",
        f"- Active persona: {c.get('active_persona_key')}",
        f"- Proactivity level: {c.get('proactivity_level')}",
        f"- Privacy mode: {c.get('privacy_mode')}",
    ])


STRICT_VALIDATORS = {
    "research_brief": validate_research_brief_strict,
    "doc_extract": validate_doc_extract_strict,
    "plan": validate_plan_strict,
    "meeting_summary": validate_meeting_summary_strict,
    "decision_matrix": validate_decision_matrix_strict,
    "action_items": validate_action_items_strict,
    "status_update": validate_status_update_strict,
    "artifact_continuity": validate_artifact_continuity_strict,
    "task_state": validate_task_state_strict,
    "proposal_action": validate_proposal_action_strict,
    "approval_token": validate_approval_token_strict,
    "executed_action": validate_executed_action_strict,
    "denied_action": validate_denied_action_strict,
    "revoked_token": validate_revoked_token_strict,
    "daily_brief": validate_daily_brief_strict,
    "heartbeat_tick": validate_heartbeat_tick_strict,
    "reminder_digest": validate_reminder_digest_strict,
    "profile_view": validate_profile_view_strict,
}

MARKDOWN_RENDERERS = {
    "research_brief": research_brief_to_markdown,
    "doc_extract": doc_extract_to_markdown,
    "plan": plan_to_markdown,
    "meeting_summary": meeting_summary_to_markdown,
    "decision_matrix": decision_matrix_to_markdown,
    "action_items": action_items_to_markdown,
    "status_update": status_update_to_markdown,
    "artifact_continuity": artifact_continuity_to_markdown,
    "task_state": task_state_to_markdown,
    "daily_brief": daily_brief_to_markdown,
    "heartbeat_tick": heartbeat_tick_to_markdown,
    "reminder_digest": reminder_digest_to_markdown,
    "profile_view": profile_view_to_markdown,
}


def validate_artifact(contract_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    validator = STRICT_VALIDATORS.get(str(contract_name or ""))
    if not validator:
        raise ValueError(f"No validator for contract={contract_name}")
    return validator(payload)
