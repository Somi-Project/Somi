from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


PROMOTION_SCOPES = {
    "conversation",
    "user_memory",
    "project_memory",
    "object_memory",
    "projects",
    "tasks",
}
STALE_SCOPES = {"profile", "preferences"}
ACTIVE_STATUSES = {"active"}
REVIEW_STATUSES = {"active", "superseded", "expired"}


def _clean(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_days(value: Any, *, now: datetime) -> int | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))


def _normalize_value(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    raw = str(row.get("payload_json") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _review_key(row: dict[str, Any]) -> str:
    slot_key = str(row.get("slot_key") or "").strip()
    if slot_key:
        return slot_key
    scope = str(row.get("scope") or "conversation").strip() or "conversation"
    key = str(row.get("mkey") or "fact").strip() or "fact"
    return f"{scope}.{key}"


def _review_item(row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    updated_at = str(row.get("updated_at") or row.get("created_at") or "").strip()
    age_days = _age_days(updated_at, now=now)
    return {
        "id": str(row.get("id") or ""),
        "key": str(row.get("mkey") or "fact").strip() or "fact",
        "review_key": _review_key(row),
        "scope": str(row.get("scope") or "conversation").strip() or "conversation",
        "value": _clean(row.get("value") or row.get("text") or "", limit=180),
        "kind": str(row.get("kind") or "preference").strip().lower() or "preference",
        "lane": str(row.get("lane") or "facts").strip().lower() or "facts",
        "status": str(row.get("status") or "active").strip().lower() or "active",
        "importance": max(0.0, min(1.0, float(row.get("importance") or 0.0))),
        "confidence": max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
        "updated_at": updated_at,
        "age_days": age_days,
        "slot_key": str(row.get("slot_key") or "").strip(),
        "mem_type": str(row.get("mem_type") or row.get("type") or "").strip().lower(),
    }


def build_memory_review(
    *,
    items: list[dict[str, Any]] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
    pinned_rows: list[dict[str, Any]] | None = None,
    summary_row: dict[str, Any] | None = None,
    preference_graph: dict[str, Any] | None = None,
    limit: int = 6,
    stale_after_days: int = 45,
    cleanup_after_days: int = 14,
) -> dict[str, Any]:
    rows = [_review_item(dict(row or {}), now=datetime.now(timezone.utc)) for row in list(items or [])]
    if not rows and not list(recent_events or []):
        return {
            "status": "idle",
            "summary": "No memory review candidates yet.",
            "alert_count": 0,
            "promotion_count": 0,
            "cleanup_count": 0,
            "conflict_count": 0,
            "stale_count": 0,
            "promotion_candidates": [],
            "cleanup_candidates": [],
            "conflict_watch": [],
            "stale_watch": [],
            "event_signal_count": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    limit = max(1, int(limit or 6))
    recent_events = list(recent_events or [])
    active_rows = [row for row in rows if row.get("status") in ACTIVE_STATUSES]
    keyed_event_counts: Counter[str] = Counter()
    keyed_touch_counts: Counter[str] = Counter()
    for event in recent_events:
        event_type = str(event.get("event_type") or "").strip().lower()
        payload = _event_payload(event)
        scope = str(payload.get("scope") or "").strip()
        key = str(payload.get("key") or payload.get("name") or "").strip()
        slot_key = str(payload.get("slot_key") or "").strip()
        review_key = slot_key or (f"{scope}.{key}" if scope and key else key)
        if not review_key:
            continue
        keyed_touch_counts[review_key] += 1
        if event_type in {"upsert", "typed_upsert"}:
            keyed_event_counts[review_key] += 1

    promotion_candidates: list[dict[str, Any]] = []
    for row in active_rows:
        if row.get("scope") not in PROMOTION_SCOPES:
            continue
        if row.get("lane") == "pinned":
            continue
        if row.get("mem_type") == "summary":
            continue
        if row.get("kind") == "volatile":
            continue
        reasons: list[str] = []
        if float(row.get("confidence") or 0.0) >= 0.84:
            reasons.append("high_confidence")
        if float(row.get("importance") or 0.0) >= 0.84:
            reasons.append("high_importance")
        if keyed_event_counts.get(str(row.get("review_key") or ""), 0) >= 2:
            reasons.append("repeated_signal")
        if row.get("scope") in {"project_memory", "projects", "tasks"}:
            reasons.append("ongoing_context")
        if not reasons:
            continue
        promotion_candidates.append(
            {
                "id": row.get("id"),
                "key": row.get("key"),
                "scope": row.get("scope"),
                "value": row.get("value"),
                "confidence": row.get("confidence"),
                "importance": row.get("importance"),
                "updated_at": row.get("updated_at"),
                "reasons": reasons,
            }
        )
    promotion_candidates.sort(
        key=lambda item: (
            -len(list(item.get("reasons") or [])),
            -float(item.get("confidence") or 0.0),
            -float(item.get("importance") or 0.0),
            str(item.get("updated_at") or ""),
        )
    )

    stale_watch: list[dict[str, Any]] = []
    for row in active_rows:
        age_days = row.get("age_days")
        if age_days is None or int(age_days) < int(stale_after_days):
            continue
        if row.get("scope") not in STALE_SCOPES and row.get("lane") != "pinned":
            continue
        stale_watch.append(
            {
                "id": row.get("id"),
                "key": row.get("key"),
                "scope": row.get("scope"),
                "value": row.get("value"),
                "age_days": int(age_days),
                "updated_at": row.get("updated_at"),
            }
        )
    stale_watch.sort(key=lambda item: (-int(item.get("age_days") or 0), str(item.get("key") or "")))

    cleanup_candidates: list[dict[str, Any]] = []
    for row in rows:
        age_days = row.get("age_days")
        if row.get("status") in {"superseded", "expired"}:
            cleanup_candidates.append(
                {
                    "id": row.get("id"),
                    "key": row.get("key"),
                    "scope": row.get("scope"),
                    "value": row.get("value"),
                    "status": row.get("status"),
                    "age_days": int(age_days or 0),
                    "reason": "history_cleanup",
                }
            )
            continue
        if row.get("status") != "active":
            continue
        if row.get("scope") not in PROMOTION_SCOPES:
            continue
        if age_days is None or int(age_days) < int(cleanup_after_days):
            continue
        if float(row.get("confidence") or 0.0) <= 0.58:
            cleanup_candidates.append(
                {
                    "id": row.get("id"),
                    "key": row.get("key"),
                    "scope": row.get("scope"),
                    "value": row.get("value"),
                    "status": row.get("status"),
                    "age_days": int(age_days),
                    "reason": "low_confidence_stale",
                }
            )
    cleanup_candidates.sort(
        key=lambda item: (
            0 if str(item.get("reason") or "") == "low_confidence_stale" else 1,
            -int(item.get("age_days") or 0),
            str(item.get("key") or ""),
        )
    )

    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"values": {}, "active_value": "", "history_count": 0, "scope": "", "key": ""}
    )
    for row in rows:
        review_key = str(row.get("review_key") or "")
        if not review_key:
            continue
        group = groups[review_key]
        group["scope"] = str(row.get("scope") or group.get("scope") or "")
        group["key"] = str(row.get("key") or group.get("key") or "")
        group["history_count"] = int(group.get("history_count") or 0) + 1
        value_key = _normalize_value(row.get("value"))
        if value_key:
            group["values"][value_key] = row.get("value")
        if row.get("status") == "active" and row.get("value"):
            group["active_value"] = row.get("value")

    conflict_watch: list[dict[str, Any]] = []
    for group in groups.values():
        values = [str(value) for value in dict(group.get("values") or {}).values() if str(value).strip()]
        if len(values) < 2:
            continue
        conflict_watch.append(
            {
                "key": str(group.get("key") or "fact"),
                "scope": str(group.get("scope") or "conversation"),
                "values": values[:4],
                "active_value": str(group.get("active_value") or ""),
                "history_count": int(group.get("history_count") or 0),
            }
        )
    conflict_watch.sort(key=lambda item: (-int(item.get("history_count") or 0), str(item.get("key") or "")))

    alert_count = len(conflict_watch) + len(stale_watch) + len(cleanup_candidates)
    status = "ready"
    if alert_count >= 5:
        status = "warn"
    elif alert_count > 0:
        status = "watch"

    preference_graph = dict(preference_graph or {})
    summary_row = dict(summary_row or {})
    pinned_rows = list(pinned_rows or [])
    lane_counts = Counter(str(row.get("lane") or "facts") for row in active_rows)
    suggested_actions: list[str] = []
    if promotion_candidates:
        suggested_actions.append("promote_repeated_memory")
    if conflict_watch:
        suggested_actions.append("review_conflicting_memory")
    if stale_watch:
        suggested_actions.append("refresh_stale_profile_memory")
    if cleanup_candidates:
        suggested_actions.append("trim_low_confidence_or_history_rows")
    summary_bits = [
        f"promote={len(promotion_candidates)}",
        f"conflicts={len(conflict_watch)}",
        f"stale={len(stale_watch)}",
        f"cleanup={len(cleanup_candidates)}",
    ]
    if int(preference_graph.get("node_count") or 0) > 0:
        summary_bits.append(f"graph={int(preference_graph.get('node_count') or 0)}")
    if summary_row:
        summary_bits.append("summary=ready")
    if pinned_rows:
        summary_bits.append(f"pinned={len(pinned_rows)}")

    return {
        "status": status,
        "summary": " | ".join(summary_bits),
        "alert_count": alert_count,
        "promotion_count": len(promotion_candidates),
        "cleanup_count": len(cleanup_candidates),
        "conflict_count": len(conflict_watch),
        "stale_count": len(stale_watch),
        "event_signal_count": sum(int(count) for count in keyed_touch_counts.values()),
        "lane_counts": dict(lane_counts),
        "suggested_actions": suggested_actions,
        "promotion_candidates": promotion_candidates[:limit],
        "cleanup_candidates": cleanup_candidates[:limit],
        "conflict_watch": conflict_watch[:limit],
        "stale_watch": stale_watch[:limit],
        "summary_ready": bool(summary_row),
        "preference_graph_nodes": int(preference_graph.get("node_count") or 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
