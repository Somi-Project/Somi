from __future__ import annotations

from pathlib import Path
from typing import Any

from workshop.toolbox.coding import CodingSessionService, get_repo_task_benchmark_pack, list_workspace_files, workspace_health_report


class CodingStudioSnapshotBuilder:
    def __init__(self, coding_service: CodingSessionService | None = None) -> None:
        self.coding_service = coding_service or CodingSessionService()

    def build(self, *, user_id: str = "default_user") -> dict[str, Any]:
        sessions = self.coding_service.list_sessions(user_id=user_id, limit=8)
        active = self.coding_service.store.get_active_session(user_id)
        session = dict(active or (sessions[0] if sessions else {}) or {})
        workspace = dict(session.get("workspace") or {})
        recent_files = [str(x) for x in list(workspace.get("recent_files") or []) if str(x).strip()]
        runtime_rows = [dict(row) for row in list(workspace.get("available_runtimes") or [])]
        metadata = dict(session.get("metadata") or {})
        health = dict(metadata.get("environment_health") or {})
        scorecard = dict(metadata.get("last_scorecard") or {})
        benchmark_pack = dict(metadata.get("benchmark_pack") or {})
        repo_map = dict(metadata.get("repo_map") or {})
        active_job = dict(metadata.get("active_job") or {})
        coding_memory = dict(metadata.get("coding_memory") or {})
        session_id = str(session.get("session_id") or "").strip()
        if session_id:
            try:
                live_job = self.coding_service.job_store.get_active_job(session_id)
            except Exception:
                live_job = None
            if isinstance(live_job, dict) and live_job:
                active_job = live_job
        sessions_rows = [
            {
                "id": str(item.get("session_id") or ""),
                "title": str(item.get("title") or "Coding Session"),
                "status": str(item.get("status") or "unknown"),
                "profile": str(dict(item.get("workspace") or {}).get("profile_key") or "python"),
                "updated_at": str(item.get("updated_at") or item.get("created_at") or ""),
            }
            for item in sessions
        ]

        workspace_files: list[dict[str, Any]] = []
        root_text = str(workspace.get("root_path") or "").strip()
        if root_text:
            root_path = Path(root_text)
            if root_path.exists():
                try:
                    workspace_files = list_workspace_files(root_path, limit=30, recursive=True)
                except Exception:
                    workspace_files = []
                if not health:
                    try:
                        health = workspace_health_report(root_path)
                    except Exception:
                        health = {}
                if not benchmark_pack:
                    try:
                        benchmark_pack = get_repo_task_benchmark_pack(
                            str(workspace.get("profile_key") or workspace.get("language") or "python"),
                            health=health,
                        )
                    except Exception:
                        benchmark_pack = {}

        return {
            "has_session": bool(session),
            "session": session,
            "workspace": workspace,
            "recent_files": recent_files,
            "runtime_rows": runtime_rows,
            "starter_files": [str(x) for x in list(workspace.get("starter_files") or []) if str(x).strip()],
            "workspace_markers": [dict(x) for x in list(workspace.get("workspace_markers") or [])],
            "workspace_files": workspace_files,
            "recent_sessions": sessions_rows,
            "next_actions": [str(x) for x in list(session.get("next_actions") or []) if str(x).strip()],
            "suggested_commands": [str(x) for x in list(workspace.get("suggested_commands") or []) if str(x).strip()],
            "skill_hint": dict(session.get("metadata") or {}).get("skill_expansion") or {},
            "health": health,
            "scorecard": scorecard,
            "benchmark_pack": benchmark_pack,
            "repo_map": repo_map,
            "active_job": active_job,
            "coding_memory": coding_memory,
        }
