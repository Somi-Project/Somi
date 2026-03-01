from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    txt = str(value).strip()
    return txt or None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        datetime.fromisoformat(txt.replace("Z", "+00:00"))
        return txt
    except Exception:
        return None


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        tag = str(item or "").strip().lower()
        if tag and tag not in out:
            out.append(tag)
    return out[:20]


def _canonical(raw: dict[str, Any], kind: str, *, strict: bool = False) -> dict[str, Any]:
    if not isinstance(raw, dict):
        if strict:
            raise ValueError(f"{kind} must be a dict")
        raw = {}

    content = dict(raw.get("content") or raw.get("data") or {})
    out = {
        "id": _as_str(raw.get("artifact_id") or raw.get("id") or content.get("id")),
        "type": kind,
        "title": _as_str(raw.get("title") or content.get("title") or content.get("summary") or raw.get("artifact_type") or kind),
        "tags": _tags(raw.get("tags") or content.get("tags") or []),
        "status": _as_str(raw.get("status") or content.get("status") or "open"),
        "created_at": _iso_or_none(raw.get("created_at") or content.get("created_at") or raw.get("timestamp")),
        "updated_at": _iso_or_none(raw.get("updated_at") or content.get("updated_at") or raw.get("timestamp")),
        "due_at": _iso_or_none(raw.get("due_at") or content.get("due_at") or content.get("deadline")),
        "thread_ref": _as_str(raw.get("thread_id") or content.get("thread_ref") or content.get("thread_id")),
        "adapter_used": "heuristic_canonical",
        "normalization_confidence": 0.65,
        "warnings": [],
    }
    if out["updated_at"] is None:
        out["updated_at"] = datetime.now(timezone.utc).isoformat()
    if strict and not out["id"]:
        raise ValueError(f"{kind}.id missing")
    return out


def _task_state_adapter(raw: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    content = dict(raw.get("content") or raw.get("data") or {})
    tasks = list(content.get("tasks") or [])
    first = dict(tasks[0] or {}) if tasks else {}
    out = {
        "id": _as_str(first.get("task_id") or raw.get("artifact_id") or raw.get("id")),
        "type": "task",
        "title": _as_str(first.get("title") or content.get("title") or "task"),
        "tags": _tags(raw.get("tags") or first.get("tags") or []),
        "status": _as_str(first.get("status") or content.get("status") or raw.get("status") or "open"),
        "created_at": _iso_or_none(first.get("created_at") or content.get("created_at") or raw.get("created_at") or raw.get("timestamp")),
        "updated_at": _iso_or_none(first.get("updated_at") or content.get("updated_at") or raw.get("updated_at") or raw.get("timestamp")),
        "due_at": _iso_or_none(first.get("due_at") or content.get("due_at") or content.get("deadline")),
        "thread_ref": _as_str(raw.get("thread_id") or content.get("thread_ref") or content.get("thread_id")),
        "adapter_used": "task_state",
        "normalization_confidence": 0.9 if first else 0.8,
        "warnings": [],
    }
    if out["updated_at"] is None:
        out["updated_at"] = datetime.now(timezone.utc).isoformat()
    if strict and not out["id"]:
        raise ValueError("task.id missing")
    return out


def _thread_adapter(raw: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    out = _canonical(raw, "thread", strict=False)
    out["adapter_used"] = "thread_adapter"
    out["normalization_confidence"] = 0.85
    if strict and not out["id"]:
        raise ValueError("thread.id missing")
    return out


ArtifactAdapter = Callable[[dict[str, Any]], dict[str, Any]]


def _adapter_map() -> dict[str, tuple[str, ArtifactAdapter]]:
    return {
        "task_state": ("task", lambda raw: _task_state_adapter(raw, strict=False)),
        "action_items": ("task", lambda raw: _canonical(raw, "task", strict=False)),
        "status_update": ("task", lambda raw: _canonical(raw, "task", strict=False)),
        "artifact_continuity": ("thread", lambda raw: _thread_adapter(raw, strict=False)),
        "plan": ("thread", lambda raw: _thread_adapter(raw, strict=False)),
        "meeting_summary": ("thread", lambda raw: _thread_adapter(raw, strict=False)),
    }


def normalize_artifact(raw: dict[str, Any], *, strict: bool = False) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("artifact must be dict")
        return None
    at = str(raw.get("artifact_type") or raw.get("contract_name") or "").strip().lower()
    amap = _adapter_map()
    if at in amap:
        expected, fn = amap[at]
        out = fn(raw)
        out["type"] = expected
        if strict and float(out.get("normalization_confidence") or 0.0) < 0.7:
            raise ValueError(f"low normalization confidence for {at}")
        return out

    if "task" in at:
        out = _canonical(raw, "task", strict=False)
        out["warnings"] = list(out.get("warnings") or []) + [f"fallback_adapter_used:{at or 'unknown'}"]
        if strict and float(out.get("normalization_confidence") or 0.0) < 0.7:
            raise ValueError(f"low normalization confidence for {at}")
        return out
    if "thread" in at:
        out = _canonical(raw, "thread", strict=False)
        out["warnings"] = list(out.get("warnings") or []) + [f"fallback_adapter_used:{at or 'unknown'}"]
        if strict and float(out.get("normalization_confidence") or 0.0) < 0.7:
            raise ValueError(f"low normalization confidence for {at}")
        return out
    if at in {"plan", "artifact_continuity"}:
        return _thread_adapter(raw, strict=strict)
    if strict:
        raise ValueError(f"unsupported artifact type: {at}")
    return None


def normalize_task(raw: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    out = normalize_artifact(raw, strict=strict)
    if not out:
        if strict:
            raise ValueError("task normalization failed")
        return _canonical(raw, "task", strict=False)
    if out.get("type") != "task":
        if strict:
            raise ValueError("not a task artifact")
        out["type"] = "task"
    return out


def normalize_thread(raw: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    out = normalize_artifact(raw, strict=strict)
    if not out:
        if strict:
            raise ValueError("thread normalization failed")
        return _canonical(raw, "thread", strict=False)
    if out.get("type") != "thread":
        if strict:
            raise ValueError("not a thread artifact")
        out["type"] = "thread"
    return out
