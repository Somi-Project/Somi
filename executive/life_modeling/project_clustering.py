from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / float(len(a | b) or 1)


def _project_id(seed_tags: list[str], seed_items: list[str]) -> str:
    seed = "|".join(seed_tags[:3] + seed_items[:2])
    return f"proj_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"


def _active(cluster: dict[str, Any], now: datetime) -> bool:
    status = str(cluster.get("status") or "active")
    updated = _parse_ts(cluster.get("updated_at"))
    has_open = int(cluster.get("open_items") or 0) > 0
    return (status != "completed" and (now - updated).days <= 90) or has_open


def _score(item: dict[str, Any], cluster: dict[str, Any], *, w: dict[str, float], recency_decay_days: int) -> tuple[float, list[str], float, float, float]:
    item_tags = set(item.get("tags") or [])
    cluster_tags = set(cluster.get("tags") or [])
    j = _jaccard(item_tags, cluster_tags)
    hits = 0
    reasons: list[str] = []
    if item.get("thread_ref") and item.get("thread_ref") in set(cluster.get("linked_thread_ids") or []):
        hits += 1
        reasons.append("thread_ref")
    overlap_items = 0
    for row in list(cluster.get("items") or []):
        if item_tags.intersection(set(row.get("tags") or [])):
            overlap_items += 1
    if overlap_items >= 2:
        hits += 1
        reasons.append("tag_overlap")

    c = min(1.0, hits / 3.0)
    age_days = max(0.0, (datetime.now(timezone.utc) - _parse_ts(item.get("updated_at"))).total_seconds() / 86400.0)
    r = math.exp(-(age_days / float(max(1, recency_decay_days))))
    s = float(w.get("tag", 0.55)) * j + float(w.get("co", 0.30)) * c + float(w.get("recency", 0.15)) * r
    return s, reasons, j, c, r


def cluster_projects(
    items: list[dict[str, Any]],
    *,
    prev_clusters: list[dict[str, Any]] | None = None,
    state_path: str = "executive/index/cluster_state.json",
    max_active_projects: int = 20,
    assign_threshold: float = 0.42,
    switch_margin: float = 0.12,
    switch_cooldown_hours: int = 72,
    min_items_per_project: int = 2,
    max_evidence_per_link: int = 5,
    weights: dict[str, float] | None = None,
    recency_decay_days: int = 21,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    weights = weights or {"tag": 0.55, "co": 0.30, "recency": 0.15}
    now = datetime.now(timezone.utc)
    clusters = [dict(c) for c in list(prev_clusters or [])]

    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    except Exception:
        state = {}
    assignments = dict(state.get("item_assignments") or {})

    for c in clusters:
        c.setdefault("items", [])
        c.setdefault("linked_item_ids", [])
        c.setdefault("linked_thread_ids", [])
        c.setdefault("tags", [])
        c.setdefault("evidence", {})

    for item in sorted(items, key=lambda x: (str(x.get("id") or ""))):
        best_idx, best_score, best_reason = None, 0.0, []
        for i, cluster in enumerate(clusters):
            score, reason_codes, *_ = _score(item, cluster, w=weights, recency_decay_days=recency_decay_days)
            if score > best_score:
                best_idx, best_score, best_reason = i, score, reason_codes

        if best_idx is None or best_score < assign_threshold:
            seed_tags = sorted(item.get("tags") or [])
            seed_items = [str(item.get("id") or "")]
            new_id = _project_id(seed_tags, seed_items)
            clusters.append(
                {
                    "artifact_type": "project_cluster",
                    "project_id": new_id,
                    "title": ", ".join(seed_tags[:3]) or f"Project {new_id[-4:]}",
                    "status": "active",
                    "tags": seed_tags[:8],
                    "items": [item],
                    "linked_item_ids": [item.get("id")],
                    "linked_thread_ids": [item.get("thread_ref")] if item.get("thread_ref") else [],
                    "evidence": {str(item.get("id") or ""): {"artifact_ids": [item.get("id")], "reason_codes": ["seed"]}},
                    "updated_at": now.isoformat(),
                }
            )
            assignments[str(item.get("id") or "")] = {"project_id": new_id, "last_switch_at": now.isoformat(), "last_score": 1.0}
            continue

        chosen = clusters[best_idx]
        item_id = str(item.get("id") or "")
        prev = assignments.get(item_id)
        if prev:
            old_pid = str(prev.get("project_id") or "")
            old_score = float(prev.get("last_score") or 0.0)
            cooldown_ok = (now - _parse_ts(prev.get("last_switch_at"))).total_seconds() >= (switch_cooldown_hours * 3600)
            if old_pid and old_pid != chosen.get("project_id"):
                if best_score < (old_score + switch_margin) or not cooldown_ok:
                    fallback = next((c for c in clusters if c.get("project_id") == old_pid), None)
                    if fallback is not None:
                        chosen = fallback

        if item_id and item_id not in set(chosen.get("linked_item_ids") or []):
            chosen.setdefault("items", []).append(item)
            chosen.setdefault("linked_item_ids", []).append(item_id)
            if item.get("thread_ref"):
                chosen.setdefault("linked_thread_ids", []).append(item.get("thread_ref"))
            chosen["linked_thread_ids"] = sorted({x for x in chosen.get("linked_thread_ids") if x})
            chosen["tags"] = sorted({*(chosen.get("tags") or []), *(item.get("tags") or [])})[:10]
            ev = chosen.setdefault("evidence", {})
            ev[item_id] = {
                "artifact_ids": [item_id][:max_evidence_per_link],
                "reason_codes": (best_reason or ["tag_overlap"])[:3],
            }
            chosen["updated_at"] = now.isoformat()
        assignments[item_id] = {"project_id": chosen.get("project_id"), "last_switch_at": now.isoformat(), "last_score": round(best_score, 4)}

    compact: list[dict[str, Any]] = []
    for cluster in clusters:
        ids = sorted({str(x) for x in list(cluster.get("linked_item_ids") or []) if x})
        open_items = len(ids)
        if open_items < min_items_per_project:
            continue
        cluster["linked_item_ids"] = ids
        cluster["open_items"] = open_items
        compact.append(cluster)

    active = [c for c in compact if _active(c, now)]
    active.sort(key=lambda c: (-int(c.get("open_items") or 0), _parse_ts(c.get("updated_at")).timestamp() * -1, str(c.get("project_id") or "")))
    active = active[:max_active_projects]

    state_payload = {"item_assignments": assignments, "updated_at": now.isoformat()}
    state_file.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for cluster in active:
        if not cluster.get("project_id"):
            tags = Counter(cluster.get("tags") or [])
            top_tags = sorted(tags, key=lambda t: (-tags[t], t))[:3]
            ids = sorted(cluster.get("linked_item_ids") or [])[:2]
            cluster["project_id"] = _project_id(top_tags or cluster.get("tags") or ["misc"], ids or ["seed"])
        cluster.pop("items", None)
    return active, state_payload
