from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


TASK_STATUS = {"open", "in_progress", "blocked", "done"}
SUBAGENT_STATUS = {"queued", "running", "completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(text: Any, *, max_len: int = 220) -> str:
    s = " ".join(str(text or "").strip().split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "..."


def _path(user_id: str, thread_id: str, root_dir: str = "sessions/task_graph") -> Path:
    uid = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(user_id or "default_user"))[:100]
    tid = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(thread_id or "general"))[:100]
    return Path(root_dir) / f"{uid}__{tid}.json"


def _default_graph(user_id: str, thread_id: str) -> Dict[str, Any]:
    return {
        "user_id": str(user_id or "default_user"),
        "thread_id": str(thread_id or "general"),
        "updated_at": _now_iso(),
        "tasks": [],
        "subagents": [],
    }


def _task_id(title: str, thread_id: str) -> str:
    raw = f"{thread_id}|{title}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _normalize_status(value: Any) -> str:
    s = str(value or "open").strip().lower()
    if s in TASK_STATUS:
        return s
    if s in {"todo", "pending"}:
        return "open"
    if s in {"working", "doing"}:
        return "in_progress"
    if s in {"complete", "completed", "finished", "resolved"}:
        return "done"
    return "open"


def _normalize_subagent_status(value: Any) -> str:
    s = str(value or "queued").strip().lower()
    if s in SUBAGENT_STATUS:
        return s
    if s in {"pending", "submitted"}:
        return "queued"
    if s in {"working", "active", "started"}:
        return "running"
    if s in {"done", "complete", "ok", "success"}:
        return "completed"
    if s in {"error"}:
        return "failed"
    return "queued"


def load_task_graph(user_id: str, thread_id: str, *, root_dir: str = "sessions/task_graph") -> Dict[str, Any]:
    p = _path(user_id, thread_id, root_dir=root_dir)
    if not p.exists():
        return _default_graph(user_id, thread_id)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _default_graph(user_id, thread_id)
    except Exception:
        return _default_graph(user_id, thread_id)

    out = _default_graph(user_id, thread_id)
    tasks = []
    for row in list(raw.get("tasks") or []):
        if not isinstance(row, dict):
            continue
        title = _safe(row.get("title"), max_len=180)
        if not title:
            continue
        tasks.append(
            {
                "task_id": str(row.get("task_id") or _task_id(title, thread_id)),
                "title": title,
                "status": _normalize_status(row.get("status")),
                "deps": [_safe(x, max_len=120) for x in list(row.get("deps") or []) if str(x).strip()][:6],
                "priority": int(row.get("priority") or 3),
                "source": _safe(row.get("source") or "conversation", max_len=40),
                "updated_at": str(row.get("updated_at") or _now_iso()),
            }
        )
    subagents = []
    for row in list(raw.get("subagents") or []):
        if not isinstance(row, dict):
            continue
        run_id = _safe(row.get("run_id"), max_len=120)
        if not run_id:
            continue
        subagents.append(
            {
                "run_id": run_id,
                "profile_key": _safe(row.get("profile_key"), max_len=80),
                "objective": _safe(row.get("objective"), max_len=220),
                "status": _normalize_subagent_status(row.get("status")),
                "child_thread_id": _safe(row.get("child_thread_id"), max_len=120),
                "summary": _safe(row.get("summary"), max_len=320),
                "artifact_refs": [_safe(x, max_len=80) for x in list(row.get("artifact_refs") or []) if str(x).strip()][:8],
                "parent_turn_id": row.get("parent_turn_id"),
                "updated_at": str(row.get("updated_at") or _now_iso()),
            }
        )
    out["tasks"] = tasks[:120]
    out["subagents"] = subagents[:40]
    out["updated_at"] = str(raw.get("updated_at") or out["updated_at"])
    return out


def save_task_graph(user_id: str, thread_id: str, graph: Dict[str, Any], *, root_dir: str = "sessions/task_graph") -> Dict[str, Any]:
    p = _path(user_id, thread_id, root_dir=root_dir)
    p.parent.mkdir(parents=True, exist_ok=True)

    out = _default_graph(user_id, thread_id)
    out["tasks"] = list(graph.get("tasks") or [])[:120]
    out["subagents"] = list(graph.get("subagents") or [])[:40]
    out["updated_at"] = _now_iso()

    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return out


def _extract_task_lines(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue

        m_checkbox = re.match(r"^[\-\*]\s*\[( |x|X)\]\s+(.+)$", line)
        if m_checkbox:
            status = "done" if m_checkbox.group(1).lower() == "x" else "open"
            out.append({"title": _safe(m_checkbox.group(2), max_len=180), "status": status})
            continue

        m_prefix = re.match(r"^(next|todo|task|pending|open loop|blocked)\s*[:\-]\s*(.+)$", line, flags=re.IGNORECASE)
        if m_prefix:
            kind = m_prefix.group(1).lower()
            status = "blocked" if kind == "blocked" else "open"
            out.append({"title": _safe(m_prefix.group(2), max_len=180), "status": status})
            continue

    return [x for x in out if str(x.get("title") or "").strip()]


def _deps_from_title(title: str) -> List[str]:
    t = str(title or "")
    deps: List[str] = []
    for m in re.finditer(r"\b(?:after|depends on|blocked by)\s+([a-z0-9 _\-]{3,80})", t, flags=re.IGNORECASE):
        deps.append(_safe(m.group(1), max_len=100))
    return deps[:4]


def update_task_graph(
    graph: Dict[str, Any],
    *,
    user_text: str,
    assistant_text: str,
    thread_id: str,
) -> Dict[str, Any]:
    out = dict(graph or {})
    tasks = list(out.get("tasks") or [])

    extracted = _extract_task_lines(user_text) + _extract_task_lines(assistant_text)
    if not extracted:
        # If user asks "what's left"/"next step", keep current graph as carry-forward.
        out["updated_at"] = _now_iso()
        out["tasks"] = tasks
        return out

    by_title = {str(t.get("title") or "").strip().lower(): dict(t) for t in tasks if str(t.get("title") or "").strip()}

    for row in extracted:
        title = _safe(row.get("title"), max_len=180)
        if not title:
            continue
        key = title.lower()
        status = _normalize_status(row.get("status"))

        existing = by_title.get(key)
        if existing:
            existing["status"] = status if status != "open" or existing.get("status") == "open" else existing.get("status")
            existing["deps"] = list(dict.fromkeys(list(existing.get("deps") or []) + _deps_from_title(title)))[:6]
            existing["updated_at"] = _now_iso()
            by_title[key] = existing
        else:
            by_title[key] = {
                "task_id": _task_id(title, thread_id),
                "title": title,
                "status": status,
                "deps": _deps_from_title(title),
                "priority": 3,
                "source": "conversation",
                "updated_at": _now_iso(),
            }

    merged = list(by_title.values())

    # Keep unfinished tasks first; retain done tasks for traceability but cap them.
    unfinished = [t for t in merged if _normalize_status(t.get("status")) != "done"]
    done = [t for t in merged if _normalize_status(t.get("status")) == "done"]
    out["tasks"] = unfinished[:80] + done[:20]
    out["updated_at"] = _now_iso()
    return out


def record_subagent_activity(
    graph: Dict[str, Any],
    *,
    run_id: str,
    profile_key: str,
    objective: str,
    status: str,
    child_thread_id: str = "",
    summary: str = "",
    artifact_refs: List[str] | None = None,
    parent_turn_id: Any = None,
) -> Dict[str, Any]:
    out = dict(graph or {})
    rows = [dict(x) for x in list(out.get("subagents") or []) if isinstance(x, dict)]
    by_run = {str(row.get("run_id") or "").strip(): row for row in rows if str(row.get("run_id") or "").strip()}

    key = str(run_id or "").strip()
    if not key:
        return out

    existing = dict(by_run.get(key) or {})
    existing["run_id"] = key
    existing["profile_key"] = _safe(profile_key, max_len=80)
    existing["objective"] = _safe(objective, max_len=220)
    existing["status"] = _normalize_subagent_status(status)
    existing["child_thread_id"] = _safe(child_thread_id, max_len=120)
    existing["summary"] = _safe(summary, max_len=320)
    existing["artifact_refs"] = [_safe(x, max_len=80) for x in list(artifact_refs or []) if str(x).strip()][:8]
    existing["parent_turn_id"] = parent_turn_id
    existing["updated_at"] = _now_iso()
    by_run[key] = existing

    priority = {"running": 0, "queued": 1, "failed": 2, "completed": 3, "cancelled": 4}
    ordered = sorted(
        by_run.values(),
        key=lambda row: (priority.get(str(row.get("status") or ""), 9), str(row.get("updated_at") or "")),
    )
    out["subagents"] = ordered[:40]
    out["updated_at"] = _now_iso()
    return out


def render_task_graph_block(graph: Dict[str, Any], *, max_items: int = 8) -> str:
    tasks = list((graph or {}).get("tasks") or [])
    open_rows = [t for t in tasks if _normalize_status(t.get("status")) != "done"]
    subagents = list((graph or {}).get("subagents") or [])
    active_subagents = [row for row in subagents if _normalize_subagent_status(row.get("status")) in {"queued", "running", "failed"}]

    lines = [
        "## Task Graph",
        f"- open_tasks: {len(open_rows)}",
        f"- active_subagents: {len([row for row in active_subagents if _normalize_subagent_status(row.get('status')) in {'queued', 'running'}])}",
        "- instruction: carry unfinished tasks across follow-ups until explicitly done",
    ]

    if not open_rows and not active_subagents:
        lines.append("- no_open_tasks: true")
        return "\n".join(lines)

    if open_rows:
        lines.append("- active:")
        for row in open_rows[:max_items]:
            title = _safe(row.get("title"), max_len=140)
            status = _normalize_status(row.get("status"))
            deps = [_safe(x, max_len=80) for x in list(row.get("deps") or []) if str(x).strip()][:3]
            if deps:
                lines.append(f"  - [{status}] {title} (deps: {', '.join(deps)})")
            else:
                lines.append(f"  - [{status}] {title}")

    if active_subagents:
        lines.append("- subagents:")
        for row in active_subagents[:max_items]:
            profile_key = _safe(row.get("profile_key"), max_len=60) or "subagent"
            status = _normalize_subagent_status(row.get("status"))
            objective = _safe(row.get("objective"), max_len=120)
            summary = _safe(row.get("summary"), max_len=120)
            if summary:
                lines.append(f"  - [{status}] {profile_key}: {objective} | {summary}")
            else:
                lines.append(f"  - [{status}] {profile_key}: {objective}")

    return "\n".join(lines)
