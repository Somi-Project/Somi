from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from workshop.toolbox.coding import (
    draft_skill_scaffold,
    load_workspace_manifest,
    resolve_workspace_root,
)
from workshop.toolbox.coding.profiles import get_language_profile
from workshop.toolbox.coding.starter_templates import scaffold_workspace


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()

    try:
        if action == "draft_skill":
            capability = str(args.get("capability") or "").strip() or "specialized capability"
            result = draft_skill_scaffold(
                skill_name=str(args.get("skill_name") or capability.title()),
                description=str(args.get("description") or f"Draft skill for {capability}"),
                capability=capability,
                objective=str(args.get("objective") or ""),
            )
            return result

        root_path = resolve_workspace_root(
            workspace_root=str(args.get("workspace_root") or ""),
            session_id=str(args.get("session_id") or ""),
            user_id=str(args.get("user_id") or ""),
        )
        manifest = load_workspace_manifest(root_path)

        if action == "bootstrap_profile":
            profile = get_language_profile(str(manifest.get("profile_key") or manifest.get("language") or "python"))
            created_files = scaffold_workspace(root_path, profile, title=str(manifest.get("title") or "Coding Workspace"))
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "profile_key": str(profile.key),
                "created_files": created_files,
            }

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
