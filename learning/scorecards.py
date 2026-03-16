from __future__ import annotations

from typing import Any

from ops import OpsControlPlane

from .trajectories import CORRECTION_MARKERS, TrajectoryStore


def _thread_rows(store: TrajectoryStore, user_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in store.list_threads(user_id=user_id, limit=200):
        rows.extend(store.load(user_id=str(item.get("user_id") or user_id), thread_id=str(item.get("thread_id") or ""), limit=400))
    return rows


def build_scorecard(
    *,
    trajectory_store: TrajectoryStore | None = None,
    ops_control: OpsControlPlane | None = None,
    user_id: str = "default_user",
) -> dict[str, Any]:
    trajectories = trajectory_store or TrajectoryStore()
    ops = ops_control or OpsControlPlane()
    rows = _thread_rows(trajectories, user_id)
    snapshot = ops.snapshot(event_limit=40, metric_limit=120)

    correction_total = 0
    grounding_total = 0
    grounding_hits = 0
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("thread_id") or "general"), []).append(row)

    for thread_rows in grouped.values():
        for idx, row in enumerate(thread_rows):
            route_name = str(row.get("route") or "").strip().lower()
            if route_name in {"websearch", "normal", "search_only", "planning"}:
                grounding_total += 1
                if bool(row.get("grounded", False)):
                    grounding_hits += 1
            if idx + 1 >= len(thread_rows):
                continue
            next_prompt = str(thread_rows[idx + 1].get("prompt") or "").lower()
            if any(marker in next_prompt for marker in CORRECTION_MARKERS):
                correction_total += 1

    total_turns = len(rows)
    correction_rate = round(correction_total / max(1, total_turns), 4)
    grounding_rate = round(grounding_hits / max(1, grounding_total), 4) if grounding_total else 1.0
    tool_metrics = dict(snapshot.get("tool_metrics") or {})
    model_metrics = dict(snapshot.get("model_metrics") or {})
    tool_success_rate = round(
        float(tool_metrics.get("successes", 0)) / max(1, int(tool_metrics.get("total", 0) or 0)),
        4,
    ) if int(tool_metrics.get("total", 0) or 0) else 1.0

    return {
        "user_id": user_id,
        "turn_count": total_turns,
        "latency_avg_ms": float(model_metrics.get("average_latency_ms", 0.0) or 0.0),
        "tool_success_rate": tool_success_rate,
        "user_correction_rate": correction_rate,
        "factual_grounding_rate": grounding_rate,
        "policy_decision_counts": dict(snapshot.get("policy_decision_counts") or {}),
        "config_revision_count": int(snapshot.get("config_revision_count", 0) or 0),
    }
