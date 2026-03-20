from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ACTIVE_BACKGROUND_STATUSES = {"queued", "running", "retry_ready", "failed"}
RESUMABLE_BACKGROUND_STATUSES = ACTIVE_BACKGROUND_STATUSES | {"completed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _surface_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if text in {"tg", "telegram"}:
        return "telegram"
    if text in {"desktop", "control_room"}:
        return "gui"
    return text


def _entry_status(*, background_statuses: list[str], task_statuses: list[str], is_active_thread: bool) -> str:
    lowered = [str(item or "").strip().lower() for item in background_statuses + task_statuses]
    if any(item == "failed" for item in lowered):
        return "warn"
    if any(item == "retry_ready" for item in lowered):
        return "watch"
    if any(item == "running" for item in lowered):
        return "running"
    if any(item == "blocked" for item in lowered):
        return "blocked"
    if any(item in {"queued", "in_progress", "open"} for item in lowered):
        return "ready" if is_active_thread else "queued"
    return "idle"


def _resume_hint(
    *,
    thread_id: str,
    surface_names: list[str],
    open_task_count: int,
    background_count: int,
    latest_route: str,
    active_thread_id: str,
) -> str:
    if background_count > 0 and "telegram" in surface_names and "gui" in surface_names:
        return f"Resume this task on either GUI or Telegram; the handoff is already shared on thread {thread_id}."
    if background_count > 0:
        return f"Resume the background handoff on thread {thread_id}."
    if open_task_count > 0 and thread_id == active_thread_id:
        return "Continue the current active thread; unfinished tasks are still open."
    if open_task_count > 0:
        return f"Resume thread {thread_id} to continue {open_task_count} unfinished task(s)."
    if latest_route:
        return f"Resume the latest {latest_route} flow on thread {thread_id}."
    return f"Resume thread {thread_id} to continue the latest cross-surface work."


def _recommended_surface(
    *,
    surface_names: list[str],
    background_count: int,
    open_task_count: int,
    primary_surface: str,
) -> str:
    surfaces = [str(item or "").strip().lower() for item in list(surface_names or []) if str(item or "").strip()]
    if background_count > 0 and "gui" in surfaces:
        return "gui"
    if open_task_count > 0 and "telegram" in surfaces:
        return "telegram"
    if primary_surface:
        return str(primary_surface)
    return surfaces[0] if surfaces else "gui"


def build_resume_ledger(
    *,
    sessions: list[dict[str, Any]] | None = None,
    background_snapshot: dict[str, Any] | None = None,
    task_graphs: dict[str, dict[str, Any]] | None = None,
    active_thread_id: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    sessions = [dict(item or {}) for item in list(sessions or []) if isinstance(item, dict)]
    background_snapshot = dict(background_snapshot or {})
    task_graphs = {str(key): dict(value or {}) for key, value in dict(task_graphs or {}).items()}
    limit = max(1, int(limit or 8))

    entry_map: dict[str, dict[str, Any]] = {}

    def ensure_entry(thread_id: str, *, session: dict[str, Any] | None = None) -> dict[str, Any]:
        key = str(thread_id or "").strip() or "__background__"
        existing = entry_map.get(key)
        if existing is not None:
            return existing
        metadata = dict((session or {}).get("metadata") or {})
        entry = {
            "thread_id": key if key != "__background__" else "",
            "session_id": str((session or {}).get("session_id") or ""),
            "user_id": str((session or {}).get("user_id") or ""),
            "surface_names": [],
            "primary_surface": _surface_label(metadata.get("surface") or metadata.get("platform") or ""),
            "conversation_ids": [],
            "last_route": str((session or {}).get("last_route") or ""),
            "last_seen_at": str((session or {}).get("last_seen_at") or ""),
            "turn_count": int((session or {}).get("turn_count") or 0),
            "open_task_count": 0,
            "blocked_task_count": 0,
            "background_count": 0,
            "retry_ready_count": 0,
            "failed_background_count": 0,
            "recent_background_statuses": [],
            "active_tasks": [],
            "background_handoffs": [],
        }
        entry_map[key] = entry
        return entry

    for session in sessions:
        thread_id = str(session.get("thread_id") or "").strip()
        if not thread_id:
            continue
        entry = ensure_entry(thread_id, session=session)
        metadata = dict(session.get("metadata") or {})
        surface = _surface_label(metadata.get("surface") or metadata.get("platform") or "")
        if surface and surface not in entry["surface_names"]:
            entry["surface_names"].append(surface)
        conversation_id = str(metadata.get("conversation_id") or "").strip()
        if conversation_id and conversation_id not in entry["conversation_ids"]:
            entry["conversation_ids"].append(conversation_id)
        if str(session.get("last_seen_at") or "") > str(entry.get("last_seen_at") or ""):
            entry["last_seen_at"] = str(session.get("last_seen_at") or "")
            entry["last_route"] = str(session.get("last_route") or "")
            entry["turn_count"] = int(session.get("turn_count") or 0)
            if surface:
                entry["primary_surface"] = surface
            if not entry.get("session_id"):
                entry["session_id"] = str(session.get("session_id") or "")
            if not entry.get("user_id"):
                entry["user_id"] = str(session.get("user_id") or "")

    for thread_id, graph in task_graphs.items():
        entry = ensure_entry(thread_id)
        open_tasks: list[dict[str, Any]] = []
        blocked_task_count = 0
        for row in list(graph.get("tasks") or []):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "open").strip().lower() or "open"
            if status == "done":
                continue
            task = {
                "task_id": str(row.get("task_id") or ""),
                "title": _clip(row.get("title") or "Task", limit=140),
                "status": status,
                "updated_at": str(row.get("updated_at") or ""),
            }
            open_tasks.append(task)
            if status == "blocked":
                blocked_task_count += 1
        entry["active_tasks"] = open_tasks[:6]
        entry["open_task_count"] = len(open_tasks)
        entry["blocked_task_count"] = blocked_task_count

    for row in list(background_snapshot.get("recent_tasks") or []):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower() or "queued"
        if status not in RESUMABLE_BACKGROUND_STATUSES:
            continue
        handoff = dict(row.get("handoff") or {})
        if status == "completed" and not handoff:
            continue
        thread_id = str(row.get("thread_id") or "").strip()
        entry = ensure_entry(thread_id or "")
        surface = _surface_label(row.get("surface") or handoff.get("surface") or "")
        if surface and surface not in entry["surface_names"]:
            entry["surface_names"].append(surface)
        entry["background_count"] = int(entry.get("background_count") or 0) + 1
        if status == "retry_ready":
            entry["retry_ready_count"] = int(entry.get("retry_ready_count") or 0) + 1
        if status == "failed":
            entry["failed_background_count"] = int(entry.get("failed_background_count") or 0) + 1
        entry["recent_background_statuses"] = list(entry.get("recent_background_statuses") or []) + [status]
        handoff_summary = _clip(
            handoff.get("summary") or row.get("summary") or row.get("recommended_action") or row.get("objective") or "",
            limit=180,
        )
        entry["background_handoffs"] = list(entry.get("background_handoffs") or []) + [
            {
                "task_id": str(row.get("task_id") or ""),
                "status": status,
                "task_type": str(row.get("task_type") or ""),
                "surface": surface,
                "summary": handoff_summary,
                "updated_at": str(row.get("updated_at") or ""),
            }
        ]
        if str(row.get("updated_at") or "") > str(entry.get("last_seen_at") or ""):
            entry["last_seen_at"] = str(row.get("updated_at") or "")
        if not entry.get("user_id"):
            entry["user_id"] = str(row.get("user_id") or "")

    entries: list[dict[str, Any]] = []
    for entry in entry_map.values():
        surfaces = sorted({str(item) for item in list(entry.get("surface_names") or []) if str(item).strip()})
        thread_id = str(entry.get("thread_id") or "").strip()
        latest_route = str(entry.get("last_route") or "").strip()
        background_statuses = [str(item) for item in list(entry.get("recent_background_statuses") or [])]
        task_statuses = [str(item.get("status") or "") for item in list(entry.get("active_tasks") or []) if isinstance(item, dict)]
        status = _entry_status(
            background_statuses=background_statuses,
            task_statuses=task_statuses,
            is_active_thread=bool(thread_id and thread_id == active_thread_id),
        )
        entry["status"] = status
        entry["surface_names"] = surfaces
        entry["is_active_thread"] = bool(thread_id and thread_id == active_thread_id)
        entry["cross_surface"] = len(surfaces) > 1
        entry["recommended_surface"] = _recommended_surface(
            surface_names=surfaces,
            background_count=int(entry.get("background_count") or 0),
            open_task_count=int(entry.get("open_task_count") or 0),
            primary_surface=str(entry.get("primary_surface") or ""),
        )
        entry["resume_hint"] = _resume_hint(
            thread_id=thread_id or "background",
            surface_names=surfaces,
            open_task_count=int(entry.get("open_task_count") or 0),
            background_count=int(entry.get("background_count") or 0),
            latest_route=latest_route,
            active_thread_id=active_thread_id,
        )
        entry["summary"] = _clip(
            " | ".join(
                part
                for part in [
                    f"surface={','.join(surfaces) or entry.get('primary_surface') or '--'}",
                    f"open={int(entry.get('open_task_count') or 0)}",
                    f"background={int(entry.get('background_count') or 0)}",
                    f"next={entry.get('recommended_surface')}" if entry.get("recommended_surface") else "",
                    f"route={latest_route}" if latest_route else "",
                ]
                if part
            ),
            limit=180,
        )
        entries.append(entry)

    priority = {"warn": 0, "watch": 1, "running": 2, "blocked": 3, "ready": 4, "queued": 5, "idle": 6}
    entries.sort(
        key=lambda row: (
            priority.get(str(row.get("status") or "idle"), 9),
            0 if bool(row.get("is_active_thread")) else 1,
            -int(row.get("background_count") or 0),
            -int(row.get("open_task_count") or 0),
            str(row.get("last_seen_at") or ""),
        )
    )

    selected = entries[:limit]
    background_total = sum(int(row.get("background_count") or 0) for row in selected)
    open_task_total = sum(int(row.get("open_task_count") or 0) for row in selected)
    cross_surface_count = sum(1 for row in selected if bool(row.get("cross_surface")))
    recommendations: list[str] = []
    if any(int(row.get("failed_background_count") or 0) > 0 for row in selected):
        recommendations.append("Resume or repair failed background tasks before starting new long-running work.")
    if any(int(row.get("retry_ready_count") or 0) > 0 for row in selected):
        recommendations.append("Retry the queued handoff tasks on the foreground surface to keep continuity intact.")
    if any(int(row.get("blocked_task_count") or 0) > 0 for row in selected):
        recommendations.append("Review blocked tasks and capture the missing dependency directly in the thread.")

    status = "idle"
    if selected:
        status = str(selected[0].get("status") or "ready")
        if status == "queued" and any(bool(row.get("is_active_thread")) for row in selected):
            status = "ready"

    return {
        "status": status,
        "entry_count": len(selected),
        "open_task_total": open_task_total,
        "background_total": background_total,
        "cross_surface_count": cross_surface_count,
        "active_thread_id": str(active_thread_id or ""),
        "summary": (
            f"entries={len(selected)} | open_tasks={open_task_total} | "
            f"background={background_total} | cross_surface={cross_surface_count}"
            if selected
            else "No resumable work is queued right now."
        ),
        "recommendations": recommendations[:4],
        "entries": selected,
        "generated_at": _now_iso(),
    }
