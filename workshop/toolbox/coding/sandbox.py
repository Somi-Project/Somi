from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import (
    CODING_SANDBOX_DEFAULT_BACKEND,
    CODING_SANDBOX_MAX_FILES,
    CODING_SANDBOX_MAX_SNAPSHOTS_PER_WORKSPACE,
    CODING_SANDBOX_MAX_TOTAL_BYTES,
    CODING_SANDBOX_PREVIEW_CHAR_THRESHOLD,
    CODING_SANDBOX_ROLLBACKS_ROOT,
    CODING_SANDBOX_SNAPSHOT_ROOT,
)
from execution_backends.factory import DEFAULT_BACKEND_REGISTRY
from workshop.toolbox.coding.profiles import get_language_profile
from workshop.toolbox.coding.runtime_inventory import build_runtime_inventory


_IGNORE_PARTS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
    ".somi_sandbox",
}
_PROTECTED_PATHS = {".git", ".venv", "node_modules"}
_WORKSPACE_MANIFEST = ".somi_coding_workspace.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, *, fallback: str = "coding") -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")[:64] or fallback


def _manifest_path(root_path: Path) -> Path:
    return root_path / _WORKSPACE_MANIFEST


def load_sandbox_manifest(root_path: Path) -> dict[str, Any]:
    path = _manifest_path(root_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_sandbox_manifest(root_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = _manifest_path(root_path)
    data = dict(payload or {})
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def workspace_key(root_path: Path) -> str:
    manifest = load_sandbox_manifest(root_path)
    return str(manifest.get("workspace_id") or root_path.name or "workspace").strip() or "workspace"


def default_task_scope(title: str) -> str:
    base = _slug(title, fallback="task")
    return f"somi/{base}"


def default_sandbox_metadata(*, title: str, backend_key: str = "", source_repo_root: str = "") -> dict[str, Any]:
    backend = str(backend_key or CODING_SANDBOX_DEFAULT_BACKEND).strip().lower() or CODING_SANDBOX_DEFAULT_BACKEND
    return {
        "sandbox_backend": backend,
        "task_scope": default_task_scope(title),
        "suggested_branch": default_task_scope(title),
        "source_repo_root": str(source_repo_root or "").strip(),
        "quotas": {
            "max_files": int(CODING_SANDBOX_MAX_FILES),
            "max_total_bytes": int(CODING_SANDBOX_MAX_TOTAL_BYTES),
            "preview_char_threshold": int(CODING_SANDBOX_PREVIEW_CHAR_THRESHOLD),
        },
    }


def seed_manifest_sandbox_fields(payload: dict[str, Any], *, title: str, backend_key: str = "", source_repo_root: str = "") -> dict[str, Any]:
    data = dict(payload or {})
    metadata = dict(data.get("metadata") or {})
    defaults = default_sandbox_metadata(title=title, backend_key=backend_key, source_repo_root=source_repo_root)
    merged = {**defaults, **metadata}
    if "quotas" in defaults or "quotas" in metadata:
        merged["quotas"] = {**dict(defaults.get("quotas") or {}), **dict(metadata.get("quotas") or {})}
    data["metadata"] = merged
    data["sandbox_backend"] = str(data.get("sandbox_backend") or merged.get("sandbox_backend") or defaults["sandbox_backend"])
    return data


def _iter_workspace_files(root_path: Path) -> list[Path]:
    rows: list[Path] = []
    for path in root_path.rglob("*"):
        if any(part in _IGNORE_PARTS for part in path.parts):
            continue
        if path.name == _WORKSPACE_MANIFEST:
            continue
        if path.is_file():
            rows.append(path)
    return rows


def build_workspace_usage(root_path: Path) -> dict[str, Any]:
    files = _iter_workspace_files(root_path)
    total_bytes = 0
    for path in files:
        try:
            total_bytes += int(path.stat().st_size)
        except OSError:
            continue
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def quota_policy(root_path: Path) -> dict[str, int]:
    manifest = load_sandbox_manifest(root_path)
    metadata = dict(manifest.get("metadata") or {})
    quotas = dict(metadata.get("quotas") or {})
    return {
        "max_files": int(quotas.get("max_files") or CODING_SANDBOX_MAX_FILES),
        "max_total_bytes": int(quotas.get("max_total_bytes") or CODING_SANDBOX_MAX_TOTAL_BYTES),
        "preview_char_threshold": int(quotas.get("preview_char_threshold") or CODING_SANDBOX_PREVIEW_CHAR_THRESHOLD),
    }


def ensure_workspace_quota(root_path: Path, *, additional_bytes: int = 0, additional_files: int = 0) -> dict[str, Any]:
    usage = build_workspace_usage(root_path)
    quota = quota_policy(root_path)
    projected_files = int(usage["file_count"]) + max(0, int(additional_files))
    projected_bytes = int(usage["total_bytes"]) + max(0, int(additional_bytes))
    if projected_files > quota["max_files"]:
        raise ValueError(f"Workspace exceeds sandbox file quota ({projected_files}>{quota['max_files']})")
    if projected_bytes > quota["max_total_bytes"]:
        raise ValueError(f"Workspace exceeds sandbox size quota ({projected_bytes}>{quota['max_total_bytes']})")
    return {
        "ok": True,
        "usage": usage,
        "quota": quota,
        "projected_files": projected_files,
        "projected_bytes": projected_bytes,
    }


def preview_workspace_write(root_path: Path, relative_path: str, content: str, *, mode: str = "overwrite") -> dict[str, Any]:
    target = (root_path / str(relative_path or "").strip()).resolve()
    if target != root_path and root_path not in target.parents:
        raise ValueError("Path escapes coding workspace")

    normalized_mode = str(mode or "overwrite").strip().lower() or "overwrite"
    existing = ""
    if target.exists() and target.is_file():
        existing = target.read_text(encoding="utf-8", errors="replace")
    incoming = str(content or "")
    if normalized_mode == "append":
        new_content = existing + incoming
    else:
        new_content = incoming

    quota = quota_policy(root_path)
    existing_chars = len(existing)
    new_chars = len(new_content)
    delta_chars = new_chars - existing_chars
    requires_preview = (
        new_chars >= quota["preview_char_threshold"]
        or abs(delta_chars) >= max(200, quota["preview_char_threshold"] // 2)
    )
    return {
        "path": target.relative_to(root_path).as_posix(),
        "exists": target.exists(),
        "mode": normalized_mode,
        "existing_chars": existing_chars,
        "new_chars": new_chars,
        "delta_chars": delta_chars,
        "requires_preview": requires_preview,
        "existing_excerpt": existing[:240],
        "incoming_excerpt": incoming[:240],
    }


def list_coding_backends(root_path: Path | None = None) -> list[dict[str, Any]]:
    inventory = build_runtime_inventory(workspace_root=str(root_path) if root_path else "")
    available_keys = {str(item).strip().lower() for item in list(inventory.get("available_keys") or []) if str(item).strip()}
    execution_backends = {str(row.get("name") or ""): dict(row) for row in DEFAULT_BACKEND_REGISTRY.list_backends()}

    managed_ready = bool({"workspace_python", "python"} & available_keys)
    return [
        {
            "key": "managed_venv",
            "label": "Managed venv",
            "execution_backend": "local",
            "available": managed_ready,
            "isolation": "managed_workspace",
            "notes": ["Uses the managed workspace root and prefers the workspace virtualenv when present."],
        },
        {
            "key": "repo_snapshot",
            "label": "Repo snapshot",
            "execution_backend": "local",
            "available": True,
            "isolation": "copy_on_write_snapshot",
            "notes": ["Copies an external repo into a managed sandbox before editing."],
        },
        {
            "key": "docker_optional",
            "label": "Docker sandbox",
            "execution_backend": "docker",
            "available": bool(dict(execution_backends.get("docker") or {}).get("available", False)),
            "isolation": "container",
            "notes": ["Reserved for a future containerized coding backend."],
        },
        {
            "key": "remote_optional",
            "label": "Remote sandbox",
            "execution_backend": "remote",
            "available": bool(dict(execution_backends.get("remote") or {}).get("available", False)),
            "isolation": "remote_worker",
            "notes": ["Reserved for a future trusted remote coding backend."],
        },
    ]


def _snapshot_root(root_path: Path) -> Path:
    return Path(CODING_SANDBOX_ROLLBACKS_ROOT) / _slug(workspace_key(root_path), fallback="workspace")


def list_workspace_snapshots(root_path: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target = _snapshot_root(root_path)
    if not target.exists():
        return rows
    for path in sorted(target.glob("*/metadata.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 12))]


def _copy_workspace_tree(source_root: Path, dest_root: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for path in source_root.rglob("*"):
        if any(part in _IGNORE_PARTS for part in path.parts):
            continue
        if path.name == _WORKSPACE_MANIFEST:
            continue
        relative = path.relative_to(source_root)
        target = dest_root / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        try:
            size = int(path.stat().st_size)
        except OSError:
            size = 0
        total_bytes += size
        file_count += 1
    return file_count, total_bytes


def create_workspace_snapshot(root_path: Path, *, label: str = "manual") -> dict[str, Any]:
    usage_report = ensure_workspace_quota(root_path)
    snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{_slug(label, fallback='snapshot')}"
    target = _snapshot_root(root_path) / snapshot_id
    content_dir = target / "content"
    content_dir.mkdir(parents=True, exist_ok=True)
    file_count, total_bytes = _copy_workspace_tree(root_path, content_dir)
    manifest = load_sandbox_manifest(root_path)
    metadata = {
        "snapshot_id": snapshot_id,
        "label": str(label or "manual"),
        "workspace_root": str(root_path),
        "workspace_id": workspace_key(root_path),
        "created_at": _now_iso(),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "sandbox_backend": str(manifest.get("sandbox_backend") or dict(manifest.get("metadata") or {}).get("sandbox_backend") or ""),
        "task_scope": str(dict(manifest.get("metadata") or {}).get("task_scope") or ""),
        "content_path": str(content_dir.resolve()),
        "usage": usage_report,
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    snapshots = list_workspace_snapshots(root_path, limit=max(1, CODING_SANDBOX_MAX_SNAPSHOTS_PER_WORKSPACE + 4))
    for stale in snapshots[CODING_SANDBOX_MAX_SNAPSHOTS_PER_WORKSPACE :]:
        stale_id = str(stale.get("snapshot_id") or "").strip()
        if stale_id:
            shutil.rmtree(_snapshot_root(root_path) / stale_id, ignore_errors=True)
    return metadata


def restore_workspace_snapshot(root_path: Path, snapshot_id: str) -> dict[str, Any]:
    snapshot_root = _snapshot_root(root_path) / str(snapshot_id or "").strip()
    content_dir = snapshot_root / "content"
    if not content_dir.exists():
        raise FileNotFoundError(f"Unknown workspace snapshot: {snapshot_id}")

    pre_restore = create_workspace_snapshot(root_path, label=f"pre_restore_{snapshot_id}")
    snapshot_rel_paths = {
        path.relative_to(content_dir).as_posix()
        for path in content_dir.rglob("*")
        if path.is_file()
    }
    for path in root_path.rglob("*"):
        if any(part in _PROTECTED_PATHS for part in path.parts):
            continue
        if path.name == _WORKSPACE_MANIFEST:
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root_path).as_posix()
        if relative not in snapshot_rel_paths:
            path.unlink(missing_ok=True)

    _copy_workspace_tree(content_dir, root_path)
    return {
        "ok": True,
        "restored_snapshot_id": str(snapshot_id),
        "workspace_root": str(root_path),
        "pre_restore_snapshot_id": str(pre_restore.get("snapshot_id") or ""),
    }


def sandbox_status(root_path: Path) -> dict[str, Any]:
    manifest = load_sandbox_manifest(root_path)
    metadata = dict(manifest.get("metadata") or {})
    usage = build_workspace_usage(root_path)
    quota = quota_policy(root_path)
    backends = list_coding_backends(root_path)
    active_backend = str(manifest.get("sandbox_backend") or metadata.get("sandbox_backend") or CODING_SANDBOX_DEFAULT_BACKEND)
    return {
        "workspace_root": str(root_path),
        "workspace_id": workspace_key(root_path),
        "active_backend": active_backend,
        "task_scope": str(metadata.get("task_scope") or ""),
        "suggested_branch": str(metadata.get("suggested_branch") or ""),
        "usage": usage,
        "quota": quota,
        "backends": backends,
        "snapshots": list_workspace_snapshots(root_path),
    }


def _infer_profile_key(root_path: Path) -> str:
    if (root_path / "tsconfig.json").exists():
        return "typescript"
    if (root_path / "package.json").exists():
        return "javascript"
    if (root_path / "index.html").exists():
        return "web"
    return "python"


def prepare_repo_snapshot_workspace(
    source_root: str | Path,
    *,
    user_id: str = "default_user",
    task_scope: str = "",
    output_root: str | Path = CODING_SANDBOX_SNAPSHOT_ROOT,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source repo not found: {source}")

    task_slug = _slug(task_scope or source.name, fallback="repo_snapshot")
    target_root = Path(output_root) / _slug(user_id, fallback="default_user") / f"{task_slug}_{uuid.uuid4().hex[:8]}"
    target_root.mkdir(parents=True, exist_ok=True)
    file_count, total_bytes = _copy_workspace_tree(source, target_root)

    if file_count > CODING_SANDBOX_MAX_FILES or total_bytes > CODING_SANDBOX_MAX_TOTAL_BYTES:
        shutil.rmtree(target_root, ignore_errors=True)
        raise ValueError("Source repo exceeds the repo snapshot sandbox quota")

    profile_key = _infer_profile_key(target_root)
    profile = get_language_profile(profile_key)
    manifest = seed_manifest_sandbox_fields(
        {
            "workspace_id": f"snapshot.{_slug(user_id)}.{target_root.name}",
            "title": f"{source.name} Snapshot",
            "root_path": str(target_root.resolve()),
            "user_id": str(user_id or "default_user"),
            "language": profile.key,
            "profile_key": profile.key,
            "profile_display_name": profile.display_name,
            "runtime_profile": profile.runtime_profile,
            "entrypoint": profile.entrypoint,
            "starter_files": list(profile.starter_files),
            "run_command": str(profile.suggested_commands[0] if profile.suggested_commands else ""),
            "test_command": str(profile.suggested_commands[1] if len(profile.suggested_commands) > 1 else ""),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "metadata": {
                "source_repo_root": str(source),
                "imported_file_count": file_count,
                "imported_total_bytes": total_bytes,
            },
        },
        title=f"{source.name} Snapshot",
        backend_key="repo_snapshot",
        source_repo_root=str(source),
    )
    save_sandbox_manifest(target_root, manifest)
    return {
        "ok": True,
        "workspace_root": str(target_root.resolve()),
        "workspace_id": str(manifest.get("workspace_id") or ""),
        "sandbox_backend": "repo_snapshot",
        "task_scope": str(dict(manifest.get("metadata") or {}).get("task_scope") or ""),
        "suggested_branch": str(dict(manifest.get("metadata") or {}).get("suggested_branch") or ""),
        "source_repo_root": str(source),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "profile_key": profile.key,
    }
