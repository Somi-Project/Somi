from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: Any, *, limit: int = 220) -> str:
    value = " ".join(str(text or "").split()).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _dedupe(items: list[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for raw in list(items or []):
        value = _clean(raw, limit=220)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(value)
    return rows[: max(0, int(limit or 0))]


def build_coding_scratchpad(
    session: dict[str, Any],
    *,
    repo_map: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    active_job: dict[str, Any] | None = None,
    coding_memory: dict[str, Any] | None = None,
    last_scorecard: dict[str, Any] | None = None,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(session or {})
    workspace = dict(payload.get("workspace") or {})
    repo_payload = dict(repo_map or {})
    job_payload = dict(active_job or {})
    health_payload = dict(health or {})
    memory_payload = dict(coding_memory or {})
    scorecard_payload = dict(last_scorecard or {})
    prior_payload = dict(prior or {})

    objective = _clean(payload.get("objective") or payload.get("last_prompt") or payload.get("title") or "", limit=280)
    next_actions = _dedupe(
        list(payload.get("next_actions") or []) + list(dict(job_payload.get("scorecard") or {}).get("next_actions") or []),
        limit=6,
    )
    focus_files = _dedupe(list(repo_payload.get("focus_files") or []), limit=5)
    constraints = _dedupe(
        list(prior_payload.get("constraints") or [])
        + ([f"Run command: {workspace.get('run_command')}"] if str(workspace.get("run_command") or "").strip() else [])
        + ([f"Verify with: {workspace.get('test_command')}"] if str(workspace.get("test_command") or "").strip() else [])
        + ([f"Environment: {health_payload.get('summary')}"] if str(health_payload.get("summary") or "").strip() else []),
        limit=5,
    )
    decisions = _dedupe(
        list(prior_payload.get("decisions") or [])
        + ([f"Repo focus: {repo_payload.get('summary')}"] if str(repo_payload.get("summary") or "").strip() else [])
        + ([f"Context memory: {memory_payload.get('summary')}"] if str(memory_payload.get("summary") or "").strip() else []),
        limit=5,
    )
    open_loops = _dedupe(
        list(prior_payload.get("open_loops") or [])
        + next_actions
        + ([f"Verification status: {scorecard_payload.get('summary')}"] if str(scorecard_payload.get("summary") or "").strip() else []),
        limit=6,
    )
    return {
        "objective": objective,
        "workspace_root": str(workspace.get("root_path") or "").strip(),
        "profile_key": str(workspace.get("profile_key") or workspace.get("language") or "python").strip() or "python",
        "focus_files": focus_files,
        "constraints": constraints,
        "decisions": decisions,
        "open_loops": open_loops,
        "next_actions": next_actions,
        "repo_summary": _clean(repo_payload.get("summary") or "", limit=220),
        "memory_summary": _clean(memory_payload.get("summary") or "", limit=220),
        "verification_summary": _clean(scorecard_payload.get("summary") or "", limit=220),
        "updated_at": _now_iso(),
    }


def build_coding_compaction_summary(
    session: dict[str, Any],
    scratchpad: dict[str, Any] | None,
    *,
    max_chars: int = 900,
) -> str:
    payload = dict(session or {})
    pad = dict(scratchpad or {})
    lines = ["[Coding Scratchpad]"]
    objective = _clean(pad.get("objective") or payload.get("objective") or payload.get("title") or "", limit=260)
    workspace_root = _clean(pad.get("workspace_root") or dict(payload.get("workspace") or {}).get("root_path") or "", limit=180)
    repo_summary = _clean(pad.get("repo_summary") or "", limit=220)
    memory_summary = _clean(pad.get("memory_summary") or "", limit=220)
    verification_summary = _clean(pad.get("verification_summary") or "", limit=220)
    if objective:
        lines.append(f"- Objective: {objective}")
    if workspace_root:
        lines.append(f"- Workspace: {workspace_root}")
    focus_files = [str(item).strip() for item in list(pad.get("focus_files") or []) if str(item).strip()]
    if focus_files:
        lines.append(f"- Focus files: {', '.join(focus_files[:4])}")
    if repo_summary:
        lines.append(f"- Repo map: {repo_summary}")
    if memory_summary:
        lines.append(f"- Context memory: {memory_summary}")
    if verification_summary:
        lines.append(f"- Verify loop: {verification_summary}")
    for row in [str(item).strip() for item in list(pad.get("open_loops") or []) if str(item).strip()][:3]:
        lines.append(f"- Open loop: {_clean(row, limit=220)}")
    for row in [str(item).strip() for item in list(pad.get("next_actions") or []) if str(item).strip()][:3]:
        lines.append(f"- Next action: {_clean(row, limit=220)}")
    summary = "\n".join(lines).strip()
    if max_chars > 0 and len(summary) > max_chars:
        summary = summary[: max_chars - 3].rstrip() + "..."
    return summary
