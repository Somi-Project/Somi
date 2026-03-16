from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workshop.toolbox.coding.models import CodingWorkspaceSnapshot
from workshop.toolbox.coding.profiles import filter_suggested_commands, get_language_profile
from workshop.toolbox.coding.runtime_inventory import build_runtime_inventory
from workshop.toolbox.coding.sandbox import seed_manifest_sandbox_fields
from workshop.toolbox.coding.starter_templates import scaffold_workspace


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str, *, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower()).strip("._-")
    return text[:64] or fallback


def _short_title(prompt: str) -> str:
    text = " ".join(str(prompt or "").strip().split())
    if not text:
        return "Coding Session"
    if len(text) <= 56:
        return text
    return text[:53].rstrip() + "..."


class CodingWorkspaceManager:
    def __init__(self, root_dir: str | Path = "workshop/tools/workspace/coding_mode") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, root_path: Path) -> Path:
        return root_path / ".somi_coding_workspace.json"

    def _collect_recent_files(self, root_path: Path, *, limit: int = 10) -> list[str]:
        ignore = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".venv", "node_modules"}
        rows: list[tuple[float, str]] = []
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignore for part in path.parts):
                continue
            if path.name == ".somi_coding_workspace.json":
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            rows.append((mtime, path.relative_to(root_path).as_posix()))
        rows.sort(key=lambda item: item[0], reverse=True)
        return [row[1] for row in rows[: max(1, int(limit or 10))]]

    def _default_entrypoint(self, profile_key: str, existing: dict[str, Any] | None = None) -> str:
        current = str(dict(existing or {}).get("entrypoint") or "").strip()
        if current:
            return current
        return get_language_profile(profile_key).entrypoint

    def ensure_workspace(
        self,
        *,
        user_id: str,
        title: str = "",
        preferred_slug: str = "",
        language: str = "python",
        profile_key: str = "",
        metadata: dict[str, Any] | None = None,
        sandbox_backend: str = "",
        source_repo_root: str = "",
    ) -> dict[str, Any]:
        safe_user = _slugify(user_id, fallback="default_user")
        title_text = str(title or "").strip() or "Coding Workspace"
        workspace_slug = _slugify(preferred_slug or title_text, fallback="workspace")
        root_path = self.root_dir / safe_user / workspace_slug
        created = not root_path.exists()
        root_path.mkdir(parents=True, exist_ok=True)
        profile = get_language_profile(profile_key or language or "python")

        manifest_path = self._manifest_path(root_path)
        current: dict[str, Any] = {}
        payload = {
            "workspace_id": f"{safe_user}.{workspace_slug}",
            "title": title_text,
            "root_path": str(root_path.as_posix()),
            "user_id": str(user_id or "default_user"),
            "language": str(language or profile.key).strip().lower() or profile.key,
            "profile_key": str(profile.key),
            "profile_display_name": str(profile.display_name),
            "runtime_profile": str(profile.runtime_profile),
            "entrypoint": str(profile.entrypoint),
            "starter_files": list(profile.starter_files),
            "run_command": str(profile.suggested_commands[0] if profile.suggested_commands else ""),
            "test_command": str(profile.suggested_commands[1] if len(profile.suggested_commands) > 1 else ""),
            "metadata": dict(metadata or {}),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        if manifest_path.exists():
            try:
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
            if isinstance(current, dict) and current:
                payload["created_at"] = str(current.get("created_at") or payload["created_at"])
                payload["profile_key"] = str(current.get("profile_key") or payload["profile_key"])
                payload["profile_display_name"] = str(current.get("profile_display_name") or payload["profile_display_name"])
                payload["runtime_profile"] = str(current.get("runtime_profile") or payload["runtime_profile"])
                payload["starter_files"] = list(current.get("starter_files") or payload["starter_files"])
                payload["run_command"] = str(current.get("run_command") or payload["run_command"])
                payload["test_command"] = str(current.get("test_command") or payload["test_command"])
                payload["metadata"] = {**dict(current.get("metadata") or {}), **dict(metadata or {})}
        payload = seed_manifest_sandbox_fields(
            payload,
            title=title_text,
            backend_key=sandbox_backend,
            source_repo_root=source_repo_root,
        )
        payload["entrypoint"] = self._default_entrypoint(str(payload["profile_key"]), current)

        if created:
            readme = root_path / "README.md"
            if not readme.exists():
                readme.write_text(
                    "# Somi Coding Workspace\n\n"
                    f"- Title: {title_text}\n"
                    f"- Language: {payload['language']}\n"
                    f"- Profile: {payload['profile_key']}\n"
                    "- Purpose: bounded workspace for coding mode sessions\n",
                    encoding="utf-8",
                )
        created_files = scaffold_workspace(root_path, get_language_profile(str(payload["profile_key"])), title=title_text)

        inventory = build_runtime_inventory(workspace_root=str(root_path))
        suggested_commands = filter_suggested_commands(
            get_language_profile(str(payload["profile_key"])),
            set(str(x) for x in list(inventory.get("available_keys") or [])),
        )
        starter_files = list(dict.fromkeys([*list(payload.get("starter_files") or []), *created_files]))
        workspace_markers = list(inventory.get("workspace_markers") or [])
        capabilities = list(get_language_profile(str(payload["profile_key"])).capabilities)
        run_command = str(payload.get("run_command") or (suggested_commands[0] if suggested_commands else ""))
        test_command = str(payload.get("test_command") or (suggested_commands[1] if len(suggested_commands) > 1 else ""))

        snapshot = CodingWorkspaceSnapshot(
            workspace_id=str(payload["workspace_id"]),
            title=str(payload["title"]),
            root_path=str(root_path.as_posix()),
            user_id=str(payload["user_id"]),
            language=str(payload["language"]),
            profile_key=str(payload["profile_key"]),
            profile_display_name=str(payload["profile_display_name"]),
            runtime_profile=str(payload["runtime_profile"]),
            sandbox_backend=str(payload.get("sandbox_backend") or ""),
            entrypoint=str(payload["entrypoint"]),
            manifest_path=str(manifest_path.as_posix()),
            recent_files=self._collect_recent_files(root_path),
            available_runtimes=list(inventory.get("runtimes") or []),
            suggested_commands=suggested_commands,
            starter_files=starter_files,
            run_command=run_command,
            test_command=test_command,
            workspace_markers=workspace_markers,
            capabilities=capabilities,
            metadata=dict(payload.get("metadata") or {}),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
        )
        snapshot_payload = snapshot.to_dict()
        manifest_payload = {
            **payload,
            "profile_display_name": snapshot_payload["profile_display_name"],
            "sandbox_backend": snapshot_payload["sandbox_backend"],
            "entrypoint": snapshot_payload["entrypoint"],
            "starter_files": snapshot_payload["starter_files"],
            "run_command": snapshot_payload["run_command"],
            "test_command": snapshot_payload["test_command"],
            "updated_at": _now_iso(),
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return snapshot.to_dict()

    def build_title(self, prompt: str) -> str:
        return _short_title(prompt)
