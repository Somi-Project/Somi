from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.coding import (
    CodingSessionStore,
    create_workspace_rollback,
    make_workspace_directory,
    preview_workspace_write_operation,
    resolve_workspace_root,
    restore_workspace_rollback,
    write_workspace_text_file,
)


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()
    store = CodingSessionStore()

    try:
        root_path = resolve_workspace_root(
            workspace_root=str(args.get("workspace_root") or ""),
            session_id=str(args.get("session_id") or ""),
            user_id=str(args.get("user_id") or ""),
            store=store,
        )

        if action in {"write_text", "append_text"}:
            payload = write_workspace_text_file(
                root_path,
                str(args.get("relative_path") or ""),
                str(args.get("content") or ""),
                mode="append" if action == "append_text" else str(args.get("if_exists") or "overwrite"),
                create_parents=bool(args.get("create_parents", True)),
                create_snapshot=bool(args.get("create_snapshot", True)),
                allow_large_write=bool(args.get("allow_large_write", False)),
                snapshot_label=str(args.get("snapshot_label") or ""),
            )
            return {"ok": True, "workspace_root": str(root_path), **payload}

        if action == "preview_write":
            payload = preview_workspace_write_operation(
                root_path,
                str(args.get("relative_path") or ""),
                str(args.get("content") or ""),
                mode=str(args.get("if_exists") or "overwrite"),
            )
            return {"ok": True, "workspace_root": str(root_path), **payload}

        if action == "mkdir":
            payload = make_workspace_directory(
                root_path,
                str(args.get("relative_path") or ""),
                parents=bool(args.get("parents", True)),
                exist_ok=bool(args.get("exist_ok", True)),
            )
            return {"ok": True, "workspace_root": str(root_path), **payload}

        if action == "create_snapshot":
            payload = create_workspace_rollback(root_path, label=str(args.get("label") or "manual"))
            return {"ok": True, "workspace_root": str(root_path), "snapshot": payload}

        if action == "restore_snapshot":
            payload = restore_workspace_rollback(root_path, str(args.get("snapshot_id") or ""))
            return {"ok": True, "workspace_root": str(root_path), **payload}

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
