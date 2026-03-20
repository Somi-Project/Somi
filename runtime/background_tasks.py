from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


TASK_STATUSES = {"queued", "running", "retry_ready", "completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _safe_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _memory_gb() -> float | None:
    if psutil is None:
        return None
    try:
        return round(float(psutil.virtual_memory().total) / float(1024**3), 2)
    except Exception:
        return None


def _cpu_count() -> int:
    try:
        return int(os.cpu_count() or 0)
    except Exception:
        return 0


def build_background_resource_budget(
    *,
    load_level: str = "normal",
    memory_gb: float | None = None,
    cpu_count: int | None = None,
) -> dict[str, Any]:
    level = str(load_level or "normal").strip().lower() or "normal"
    memory = float(memory_gb if memory_gb is not None else (_memory_gb() or 0.0))
    cpus = int(cpu_count if cpu_count is not None else _cpu_count())

    if level == "critical":
        max_concurrent = 0
        heavy_allowed = False
        max_parallel_tools = 1
    elif level == "high":
        max_concurrent = 1
        heavy_allowed = memory >= 12.0 and cpus >= 6
        max_parallel_tools = 1
    elif level == "medium":
        max_concurrent = 1 if memory < 8.0 else 2
        heavy_allowed = memory >= 16.0 and cpus >= 8
        max_parallel_tools = 2
    else:
        max_concurrent = 1 if memory < 6.0 else (2 if memory < 16.0 else 3)
        heavy_allowed = memory >= 12.0 and cpus >= 6
        max_parallel_tools = 2 if memory < 12.0 else 3

    return {
        "load_level": level,
        "memory_gb": memory,
        "cpu_count": cpus,
        "max_concurrent_tasks": max_concurrent,
        "max_parallel_tools_per_task": max_parallel_tools,
        "heavy_task_allowed": bool(heavy_allowed and max_concurrent > 0),
        "notes": (
            "Prefer light background work until the runtime load drops."
            if level in {"high", "critical"}
            else "Background work can proceed within the current local budget."
        ),
    }


class BackgroundTaskStore:
    def __init__(self, root_dir: str | Path = "sessions/background_tasks") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.root_dir / f"{str(task_id or '').strip()}.json"

    def _write_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        data["updated_at"] = str(data.get("updated_at") or _now_iso())
        path = self._task_path(str(data.get("task_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def create_task(
        self,
        *,
        user_id: str,
        objective: str,
        task_type: str,
        surface: str = "gui",
        thread_id: str = "",
        max_retries: int = 2,
        artifacts: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "task_id": f"bgtask_{uuid.uuid4().hex[:12]}",
            "user_id": str(user_id or "default_user"),
            "thread_id": str(thread_id or ""),
            "task_type": str(task_type or "background").strip().lower() or "background",
            "surface": str(surface or "gui").strip().lower() or "gui",
            "objective": _safe_text(objective, limit=260),
            "status": "queued",
            "summary": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "started_at": "",
            "completed_at": "",
            "retry_count": 0,
            "max_retries": max(0, int(max_retries or 0)),
            "last_error": "",
            "recommended_action": "",
            "artifacts": [dict(item) for item in list(artifacts or []) if isinstance(item, dict)][:12],
            "meta": dict(meta or {}),
            "handoff": {},
        }
        return self._write_task(payload)

    def list_tasks(
        self,
        *,
        user_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        allowed = {str(item).strip().lower() for item in set(statuses or set()) if str(item).strip()}
        for path in sorted(self.root_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = self.load_task(path.stem)
            if not isinstance(payload, dict):
                continue
            if user_id and str(payload.get("user_id") or "") != str(user_id):
                continue
            status = str(payload.get("status") or "").strip().lower()
            if allowed and status not in allowed:
                continue
            rows.append(payload)
            if len(rows) >= max(1, int(limit or 24)):
                break
        return rows

    def heartbeat(
        self,
        task_id: str,
        *,
        status: str = "running",
        summary: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.load_task(task_id)
        if not isinstance(payload, dict):
            raise ValueError(f"Unknown background task: {task_id}")
        payload["status"] = "running" if str(status or "").strip().lower() not in TASK_STATUSES else str(status).strip().lower()
        payload["summary"] = _safe_text(summary or payload.get("summary") or "", limit=320)
        payload["started_at"] = str(payload.get("started_at") or _now_iso())
        payload["updated_at"] = _now_iso()
        if artifacts:
            payload["artifacts"] = [dict(item) for item in list(artifacts or []) if isinstance(item, dict)][:12]
        if meta:
            merged = dict(payload.get("meta") or {})
            merged.update(dict(meta or {}))
            payload["meta"] = merged
        return self._write_task(payload)

    def complete_task(
        self,
        task_id: str,
        *,
        summary: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.load_task(task_id)
        if not isinstance(payload, dict):
            raise ValueError(f"Unknown background task: {task_id}")
        payload["status"] = "completed"
        payload["summary"] = _safe_text(summary or payload.get("summary") or "", limit=320)
        payload["completed_at"] = _now_iso()
        payload["updated_at"] = payload["completed_at"]
        if artifacts:
            payload["artifacts"] = [dict(item) for item in list(artifacts or []) if isinstance(item, dict)][:12]
        if handoff:
            payload["handoff"] = dict(handoff or {})
        return self._write_task(payload)

    def fail_task(
        self,
        task_id: str,
        *,
        error: str,
        recoverable: bool = True,
        recommended_action: str = "",
    ) -> dict[str, Any]:
        payload = self.load_task(task_id)
        if not isinstance(payload, dict):
            raise ValueError(f"Unknown background task: {task_id}")
        payload["last_error"] = _safe_text(error, limit=260)
        payload["recommended_action"] = _safe_text(
            recommended_action or "Retry with a lighter plan or hand the task back to the active surface.",
            limit=220,
        )
        if recoverable and int(payload.get("retry_count") or 0) < int(payload.get("max_retries") or 0):
            payload["status"] = "retry_ready"
            payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
        else:
            payload["status"] = "failed"
        payload["updated_at"] = _now_iso()
        return self._write_task(payload)

    def recover_stalled_tasks(self, *, stale_after_seconds: int = 900) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_after_seconds or 900)))
        for payload in self.list_tasks(limit=200):
            status = str(payload.get("status") or "").strip().lower()
            if status not in {"queued", "running"}:
                continue
            updated_at = _utc_datetime(payload.get("updated_at"))
            if updated_at is None or updated_at >= cutoff:
                continue
            payload["last_error"] = _safe_text("Task heartbeat expired before completion.", limit=220)
            payload["recommended_action"] = _safe_text(
                "Resume on the foreground surface or retry with a lighter background budget.",
                limit=220,
            )
            if int(payload.get("retry_count") or 0) < int(payload.get("max_retries") or 0):
                payload["status"] = "retry_ready"
                payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
            else:
                payload["status"] = "failed"
            payload["updated_at"] = _now_iso()
            recovered.append(self._write_task(payload))
        return recovered

    def snapshot(self, *, user_id: str | None = None, limit: int = 12, load_level: str = "normal") -> dict[str, Any]:
        rows = self.list_tasks(user_id=user_id, limit=limit)
        counts: dict[str, int] = {}
        for row in self.list_tasks(user_id=user_id, limit=200):
            status = str(row.get("status") or "queued").strip().lower() or "queued"
            counts[status] = counts.get(status, 0) + 1
        return {
            "counts": counts,
            "recent_tasks": rows,
            "resource_budget": build_background_resource_budget(load_level=load_level),
            "running_count": int(counts.get("running", 0)),
            "retry_ready_count": int(counts.get("retry_ready", 0)),
            "failed_count": int(counts.get("failed", 0)),
            "updated_at": _now_iso(),
        }
