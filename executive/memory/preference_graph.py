from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _clean(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(row.get("mkey") or row.get("key") or "").strip(),
        "value": _clean(row.get("value") or row.get("text") or "", limit=180),
        "kind": str(row.get("kind") or "preference").strip().lower() or "preference",
        "confidence": max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
        "updated_at": str(row.get("updated_at") or row.get("created_at") or "").strip(),
    }


def build_preference_graph(
    *,
    profile_rows: list[dict[str, Any]] | None = None,
    preference_rows: list[dict[str, Any]] | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    node_map: dict[str, dict[str, Any]] = {}
    for row in list(profile_rows or []) + list(preference_rows or []):
        item = _normalize_row(dict(row or {}))
        key = str(item.get("key") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        if not key or not value:
            continue
        node_key = f"{key}:{value.lower()}"
        node = node_map.get(node_key)
        if node is None:
            node = {
                "key": key,
                "value": value,
                "kind": item.get("kind") or "preference",
                "confidence": float(item.get("confidence") or 0.0),
                "evidence_count": 1,
                "updated_at": item.get("updated_at") or "",
            }
            node_map[node_key] = node
            nodes.append(node)
            continue
        node["confidence"] = max(float(node.get("confidence") or 0.0), float(item.get("confidence") or 0.0))
        node["evidence_count"] = int(node.get("evidence_count") or 0) + 1
        current_updated = str(node.get("updated_at") or "")
        incoming_updated = str(item.get("updated_at") or "")
        if incoming_updated and incoming_updated > current_updated:
            node["updated_at"] = incoming_updated

    nodes.sort(
        key=lambda item: (
            0 if str(item.get("kind") or "") == "profile" else 1,
            -float(item.get("confidence") or 0.0),
            -int(item.get("evidence_count") or 0),
            str(item.get("key") or ""),
        )
    )
    selected = nodes[: max(1, int(limit or 24))]
    summary = " | ".join(
        f"{row.get('key')}={_clean(row.get('value') or '', limit=36)} ({float(row.get('confidence') or 0.0):.2f})"
        for row in selected[:6]
    )
    return {
        "summary": summary or "No preference graph data yet.",
        "node_count": len(selected),
        "profile_count": sum(1 for row in selected if str(row.get("kind") or "") == "profile"),
        "preference_count": sum(1 for row in selected if str(row.get("kind") or "") != "profile"),
        "nodes": selected,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
