from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_context_pack(
    projects: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    heartbeat_v2: dict[str, Any],
    patterns: list[dict[str, Any]],
    calendar_snapshot: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    def rank(p: dict[str, Any]) -> tuple[int, float, str]:
        updated = p.get("updated_at")
        recency = 0.0
        try:
            recency = -(now - datetime.fromisoformat(str(updated).replace("Z", "+00:00"))).total_seconds()
        except Exception:
            recency = -1e18
        return (int(p.get("open_items") or 0), recency, str(p.get("project_id") or ""))

    top_projects = sorted(projects, key=rank, reverse=True)[:10]
    impacts = list(heartbeat_v2.get("impacts") or [])[:5]
    patt = sorted(patterns, key=lambda x: float(x.get("confidence") or 0.0), reverse=True)[:3]
    conflicts = list(calendar_snapshot.get("conflicts") or [])[:3]

    rel: set[str] = set()
    for p in top_projects:
        rel.add(str(p.get("project_id") or ""))
        for it in list(p.get("linked_item_ids") or [])[:10]:
            rel.add(str(it))
    for g in goals:
        rel.add(str(g.get("goal_id") or ""))
    for i in impacts:
        for eid in list(i.get("evidence_artifact_ids") or []):
            rel.add(str(eid))

    rel.discard("")
    return {
        "artifact_type": "context_pack_v1",
        "projects": top_projects,
        "confirmed_goals": goals,
        "top_impacts": impacts,
        "patterns": patt,
        "calendar_conflicts": conflicts,
        "relevant_artifact_ids": sorted(rel),
    }
