from __future__ import annotations

from typing import Any


def build_heartbeat_v2(
    items: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    confirmed_goals: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    calendar_snapshot: dict[str, Any],
) -> dict[str, Any]:
    proj_map = {str(p.get("project_id") or ""): p for p in projects}
    goal_map: dict[str, list[str]] = {}
    for g in confirmed_goals:
        goal_map[str(g.get("goal_id") or "")] = list(g.get("linked_project_ids") or [])

    impacts: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        pid = _find_project(item_id, projects)
        gid = _find_goal(pid, goal_map)
        overdue = bool(item.get("due_at")) and str(item.get("status") or "") not in {"done", "closed"}
        active_proj = bool(pid and int(proj_map.get(pid, {}).get("open_items") or 0) > 0)
        at_risk_goal = bool(gid)
        if overdue and active_proj and at_risk_goal:
            level = "high"
        elif overdue or active_proj:
            level = "moderate"
        else:
            level = "low"
        impacts.append(
            {
                "level": level,
                "task_id": item_id,
                "project_id": pid,
                "goal_id": gid,
                "evidence_artifact_ids": [x for x in [item_id, pid, gid] if x],
            }
        )

    impacts.sort(key=lambda x: ({"high": 0, "moderate": 1, "low": 2}[x["level"]], str(x.get("task_id") or "")))
    summary = f"{len(impacts)} impacts across {len(projects)} projects, {len(patterns)} patterns, {len(calendar_snapshot.get('conflicts') or [])} calendar conflicts."

    evidence = sorted({eid for row in impacts for eid in row.get("evidence_artifact_ids") or []})
    return {
        "artifact_type": "heartbeat_v2",
        "summary": summary,
        "impacts": impacts,
        "patterns": patterns,
        "calendar_conflicts": list(calendar_snapshot.get("conflicts") or []),
        "evidence_artifact_ids": evidence,
    }


def _find_project(item_id: str, projects: list[dict[str, Any]]) -> str | None:
    for p in projects:
        if item_id in set(p.get("linked_item_ids") or []):
            return str(p.get("project_id") or "") or None
    return None


def _find_goal(project_id: str | None, goal_map: dict[str, list[str]]) -> str | None:
    if not project_id:
        return None
    for gid, pids in goal_map.items():
        if project_id in set(pids):
            return gid
    return None
