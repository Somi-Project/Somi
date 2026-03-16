from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMAS: dict[str, dict[str, Any]] = {
    "project_cluster": {
        "artifact_type": "project_cluster",
        "project_id": "",
        "title": "",
        "status": "active",
        "tags": [],
        "open_items": 0,
        "linked_item_ids": [],
        "linked_thread_ids": [],
        "evidence": {},
        "updated_at": None,
    },
    "goal_model": {
        "artifact_type": "goal_model",
        "goal_id": "",
        "title": "",
        "confirmed": True,
        "linked_project_ids": [],
        "updated_at": None,
    },
    "goal_link_proposal": {
        "artifact_type": "goal_link_proposal",
        "proposal_id": "",
        "goal_id": "",
        "project_id": "",
        "evidence_artifact_ids": [],
        "reason_codes": [],
        "requires_confirmation": True,
        "updated_at": None,
    },
    "goal_candidate": {
        "artifact_type": "goal_candidate",
        "candidate_id": "",
        "title": "",
        "evidence_artifact_ids": [],
        "requires_confirmation": True,
        "updated_at": None,
    },
    "pattern_insight": {
        "artifact_type": "pattern_insight",
        "pattern_id": "",
        "pattern_type": "",
        "description": "",
        "confidence": 0.0,
        "intervention": "",
        "evidence_artifact_ids": [],
        "window_days": 30,
        "updated_at": None,
    },
    "calendar_snapshot": {
        "artifact_type": "calendar_snapshot",
        "window_start": None,
        "window_end": None,
        "events": [],
        "conflicts": [],
        "updated_at": None,
    },
    "heartbeat_v2": {
        "artifact_type": "heartbeat_v2",
        "summary": "",
        "impacts": [],
        "patterns": [],
        "calendar_conflicts": [],
        "evidence_artifact_ids": [],
        "updated_at": None,
    },
    "context_pack_v1": {
        "artifact_type": "context_pack_v1",
        "projects": [],
        "confirmed_goals": [],
        "top_impacts": [],
        "patterns": [],
        "calendar_conflicts": [],
        "relevant_artifact_ids": [],
        "updated_at": None,
    },
}


def schema_for(artifact_type: str) -> dict[str, Any]:
    base = deepcopy(SCHEMAS.get(str(artifact_type or ""), {}))
    if base and not base.get("updated_at"):
        base["updated_at"] = _utc_now_iso()
    return base


def inject_schema(artifact_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    base = schema_for(artifact_type)
    out = dict(base)
    out.update(dict(payload or {}))
    if "artifact_type" not in out:
        out["artifact_type"] = artifact_type
    if not out.get("updated_at"):
        out["updated_at"] = _utc_now_iso()
    return out
