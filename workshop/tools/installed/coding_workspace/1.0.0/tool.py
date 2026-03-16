from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.coding import CodingSessionStore, list_workspace_files, read_workspace_text_file, resolve_workspace_root
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.repo_map import build_repo_map


def _session_payload(store: CodingSessionStore, args: dict[str, Any]) -> dict[str, Any]:
    session_id = str(args.get("session_id") or "").strip()
    user_id = str(args.get("user_id") or "").strip()
    if session_id:
        session = store.load_session(session_id)
    elif user_id:
        session = store.get_active_session(user_id)
    else:
        raise ValueError("session_id or user_id is required for session_status")
    if not isinstance(session, dict):
        raise ValueError("Coding session not found")
    return session


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()
    store = CodingSessionStore()

    try:
        if action == "session_status":
            session = _session_payload(store, args)
            active_job = CodingJobStore().get_active_job(str(session.get("session_id") or ""))
            return {
                "ok": True,
                "session": session,
                "active_job": active_job or {},
                "workspace_root": str(dict(session.get("workspace") or {}).get("root_path") or ""),
            }

        root_path = resolve_workspace_root(
            workspace_root=str(args.get("workspace_root") or ""),
            session_id=str(args.get("session_id") or ""),
            user_id=str(args.get("user_id") or ""),
            store=store,
        )

        if action == "list_files":
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "files": list_workspace_files(
                    root_path,
                    limit=int(args.get("limit") or 50),
                    recursive=bool(args.get("recursive", True)),
                ),
            }

        if action == "read_file":
            payload = read_workspace_text_file(
                root_path,
                str(args.get("relative_path") or ""),
                max_chars=int(args.get("max_chars") or 12000),
            )
            return {
                "ok": True,
                "workspace_root": str(root_path),
                **payload,
            }

        if action == "repo_map":
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "repo_map": build_repo_map(root_path, objective=str(args.get("objective") or "")),
            }

        if action == "job_status":
            session_id = str(args.get("session_id") or "").strip()
            if not session_id:
                session = store.get_active_session(str(args.get("user_id") or "").strip())
                session_id = str(dict(session or {}).get("session_id") or "").strip()
            job = CodingJobStore().get_active_job(session_id) if session_id else None
            return {"ok": True, "workspace_root": str(root_path), "job": job or {}}

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
