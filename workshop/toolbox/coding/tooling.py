from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from config.settings import CODING_SANDBOX_SNAPSHOT_ROOT
from execution_backends.base import BackendExecutionRequest, ExecutionBackendError
from execution_backends.factory import DEFAULT_BACKEND_REGISTRY
from workshop.toolbox.coding.benchmarks import get_repo_task_benchmark_pack
from workshop.toolbox.coding.runtime_inventory import build_runtime_inventory
from workshop.toolbox.coding.sandbox import (
    build_workspace_usage,
    create_workspace_snapshot,
    ensure_workspace_quota,
    list_coding_backends,
    list_workspace_snapshots,
    prepare_repo_snapshot_workspace,
    preview_workspace_write,
    quota_policy,
    restore_workspace_snapshot,
    sandbox_status,
)
from workshop.toolbox.coding.scorecards import build_coding_run_scorecard, build_environment_health
from workshop.toolbox.coding.store import CodingSessionStore


_IGNORE_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".venv", "node_modules"}
_WORKSPACE_MANIFEST = ".somi_coding_workspace.json"
_WRITE_CHAR_CAP = 200_000


def _resolve_store(store: CodingSessionStore | None = None) -> CodingSessionStore:
    return store or CodingSessionStore()


def resolve_workspace_root(
    *,
    workspace_root: str = "",
    session_id: str = "",
    user_id: str = "",
    store: CodingSessionStore | None = None,
) -> Path:
    resolved_store = _resolve_store(store)
    target_root = str(workspace_root or "").strip()

    if not target_root and session_id:
        session = resolved_store.load_session(session_id)
        if not isinstance(session, dict):
            raise ValueError(f"Unknown coding session: {session_id}")
        target_root = str(dict(session.get("workspace") or {}).get("root_path") or "").strip()

    if not target_root and user_id:
        session = resolved_store.get_active_session(user_id)
        if not isinstance(session, dict):
            raise ValueError(f"No active coding session for user: {user_id}")
        target_root = str(dict(session.get("workspace") or {}).get("root_path") or "").strip()

    if not target_root:
        raise ValueError("workspace_root, session_id, or user_id is required")

    root_path = Path(target_root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Workspace root does not exist: {root_path}")
    if not (root_path / _WORKSPACE_MANIFEST).exists():
        raise ValueError(f"Workspace is not managed by coding mode: {root_path}")
    return root_path


def resolve_workspace_path(
    root_path: Path,
    relative_path: str,
    *,
    require_exists: bool = False,
    allow_root: bool = False,
) -> Path:
    rel = str(relative_path or "").strip().replace("\\", "/")
    if not rel:
        if allow_root:
            return root_path
        raise ValueError("relative_path is required")
    if Path(rel).is_absolute():
        raise ValueError("relative_path must be relative")

    candidate = (root_path / rel).resolve()
    if candidate != root_path and root_path not in candidate.parents:
        raise ValueError("Path escapes coding workspace")
    if require_exists and not candidate.exists():
        raise FileNotFoundError(f"Workspace path does not exist: {rel}")
    return candidate


def load_workspace_manifest(root_path: Path) -> dict[str, Any]:
    manifest_path = root_path / _WORKSPACE_MANIFEST
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def workspace_profile_key(root_path: Path) -> str:
    manifest = load_workspace_manifest(root_path)
    return str(manifest.get("profile_key") or manifest.get("language") or "python").strip().lower() or "python"


def workspace_backend_key(root_path: Path) -> str:
    manifest = load_workspace_manifest(root_path)
    return str(manifest.get("sandbox_backend") or dict(manifest.get("metadata") or {}).get("sandbox_backend") or "managed_venv").strip().lower() or "managed_venv"


def sandbox_status_report(root_path: Path) -> dict[str, Any]:
    return sandbox_status(root_path)


def preview_workspace_write_operation(root_path: Path, relative_path: str, content: str, *, mode: str = "overwrite") -> dict[str, Any]:
    return preview_workspace_write(root_path, relative_path, content, mode=mode)


def preferred_python_command(root_path: Path) -> list[str]:
    inventory = build_runtime_inventory(workspace_root=str(root_path))
    for row in list(inventory.get("runtimes") or []):
        if str(row.get("key") or "") == "workspace_python" and bool(row.get("available")) and str(row.get("path") or "").strip():
            return [str(row.get("path"))]
    return [str(sys.executable)]


def _normalize_workspace_argv(root_path: Path, argv: list[str]) -> list[str]:
    normalized = [str(x) for x in list(argv or []) if str(x).strip()]
    if not normalized:
        return normalized
    head = normalized[0].strip().lower()
    if head == "python":
        return [*preferred_python_command(root_path), *normalized[1:]]
    if head == "pytest":
        return [*preferred_python_command(root_path), "-m", "pytest", *normalized[1:]]
    return normalized


def run_workspace_command(
    root_path: Path,
    command: str | list[str],
    *,
    timeout_s: int = 30,
    output_cap: int = 20000,
    extra_env: dict[str, str] | None = None,
    backend_key: str = "",
) -> dict[str, Any]:
    argv = (
        [str(x) for x in list(command or []) if str(x).strip()]
        if isinstance(command, list)
        else shlex.split(str(command or ""), posix=(os.name != "nt"))
    )
    if not argv:
        raise ValueError("command is required")
    argv = _normalize_workspace_argv(root_path, argv)
    return run_command_in_workspace(
        root_path,
        argv,
        timeout_s=timeout_s,
        output_cap=output_cap,
        extra_env=extra_env,
        backend_key=backend_key,
    )


def run_node_script(
    root_path: Path,
    relative_path: str,
    *,
    script_args: list[str] | None = None,
    timeout_s: int = 30,
    output_cap: int = 20000,
    backend_key: str = "",
) -> dict[str, Any]:
    script_path = resolve_workspace_path(root_path, relative_path, require_exists=True)
    argv = ["node", script_path.relative_to(root_path).as_posix(), *[str(x) for x in list(script_args or [])]]
    return run_command_in_workspace(root_path, argv, timeout_s=timeout_s, output_cap=output_cap, backend_key=backend_key)


def run_npm_script(
    root_path: Path,
    script_name: str,
    *,
    script_args: list[str] | None = None,
    timeout_s: int = 45,
    output_cap: int = 20000,
    backend_key: str = "",
) -> dict[str, Any]:
    name = str(script_name or "").strip()
    if not name:
        raise ValueError("script_name is required")
    argv = ["npm", "run", name]
    extra = [str(x) for x in list(script_args or []) if str(x).strip()]
    if extra:
        argv.extend(["--", *extra])
    return run_command_in_workspace(root_path, argv, timeout_s=timeout_s, output_cap=output_cap, backend_key=backend_key)


def run_npx_command(
    root_path: Path,
    command_args: list[str],
    *,
    timeout_s: int = 45,
    output_cap: int = 20000,
    backend_key: str = "",
) -> dict[str, Any]:
    argv = ["npx", *[str(x) for x in list(command_args or []) if str(x).strip()]]
    if len(argv) == 1:
        raise ValueError("command_args is required")
    return run_command_in_workspace(root_path, argv, timeout_s=timeout_s, output_cap=output_cap, backend_key=backend_key)


def preview_static_workspace(root_path: Path) -> dict[str, Any]:
    manifest = load_workspace_manifest(root_path)
    entrypoint = str(manifest.get("entrypoint") or "index.html").strip() or "index.html"
    target = resolve_workspace_path(root_path, entrypoint, require_exists=False)
    return {
        "workspace_root": str(root_path),
        "entrypoint": entrypoint,
        "exists": target.exists(),
        "path": str(target),
        "suggested_url": f"http://127.0.0.1:8000/{entrypoint.replace(os.sep, '/')}",
    }


def workspace_health_report(root_path: Path, *, refresh: bool = False) -> dict[str, Any]:
    return build_environment_health(root_path, refresh=refresh)


def _command_prefix(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    return text.split()[0].strip().lower()


def _verify_step_result(
    *,
    name: str,
    label: str,
    required: bool,
    status: str,
    ok: bool,
    elapsed_ms: int = 0,
    command: str = "",
    stdout: str = "",
    stderr: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "required": bool(required),
        "status": str(status),
        "ok": bool(ok),
        "elapsed_ms": int(elapsed_ms or 0),
        "command": str(command or ""),
        "stdout": str(stdout or ""),
        "stderr": str(stderr or ""),
        "error": str(error or ""),
    }


def _blocked_command_result(name: str, label: str, command: str, reason: str, *, required: bool) -> dict[str, Any]:
    return _verify_step_result(
        name=name,
        label=label,
        required=required,
        status="blocked",
        ok=False,
        command=command,
        error=reason,
        stderr=reason,
    )


def _should_block_command(command: str, health: dict[str, Any]) -> str:
    prefix = _command_prefix(command)
    if not prefix:
        return "No command configured"
    if prefix in {"npm", "npx", "pnpm", "bun"} and bool(health.get("dependency_install_required")):
        return "Project dependencies are not installed yet"
    available = {str(item).strip().lower() for item in list(health.get("available_runtime_keys") or []) if str(item).strip()}
    if prefix == "python" and not ({"workspace_python", "python"} & available):
        return "Python runtime is not available"
    if prefix == "node" and "node" not in available:
        return "Node runtime is not available"
    if prefix == "npm" and "npm" not in available:
        return "npm is not available"
    if prefix == "npx" and "npx" not in available:
        return "npx is not available"
    if prefix == "pnpm" and "pnpm" not in available:
        return "pnpm is not available"
    if prefix == "bun" and "bun" not in available:
        return "bun is not available"
    return ""


def run_verify_loop(
    root_path: Path,
    *,
    timeout_s: int = 45,
    output_cap: int = 20000,
) -> dict[str, Any]:
    manifest = load_workspace_manifest(root_path)
    profile_key = workspace_profile_key(root_path)
    health = workspace_health_report(root_path, refresh=True)
    benchmark_pack = get_repo_task_benchmark_pack(profile_key, health=health)

    steps: list[dict[str, Any]] = [
        _verify_step_result(
            name="workspace_health",
            label="Workspace health",
            required=True,
            status="executed",
            ok=bool(health.get("ok", False)),
            command="workspace_health_report",
        )
    ]

    if profile_key in {"web", "game"}:
        preview = preview_static_workspace(root_path)
        steps.append(
            _verify_step_result(
                name="preview_entrypoint",
                label="Preview entrypoint",
                required=True,
                status="executed",
                ok=bool(preview.get("exists", False)),
                command=str(preview.get("entrypoint") or ""),
                error="" if bool(preview.get("exists", False)) else f"Missing entrypoint: {preview.get('entrypoint')}",
            )
        )
        scorecard = build_coding_run_scorecard(root_path=root_path, health=health, steps=steps, benchmark_pack=benchmark_pack)
        return {
            "ok": bool(scorecard.get("status") != "red"),
            "workspace_root": str(root_path),
            "profile_key": profile_key,
            "health": health,
            "steps": steps,
            "benchmark_pack": benchmark_pack,
            "preview": preview,
            "scorecard": scorecard,
            "next_actions": list(scorecard.get("next_actions") or []),
        }

    command_specs = [
        ("run_command", "Run command", str(manifest.get("run_command") or "").strip()),
        ("test_command", "Test command", str(manifest.get("test_command") or "").strip()),
    ]
    for name, label, command in command_specs:
        if not command:
            steps.append(
                _verify_step_result(
                    name=name,
                    label=label,
                    required=(name == "test_command"),
                    status="skipped",
                    ok=(name != "test_command"),
                    error="No command configured",
                )
            )
            continue
        blocked_reason = _should_block_command(command, health)
        if blocked_reason:
            steps.append(_blocked_command_result(name, label, command, blocked_reason, required=(name == "test_command")))
            continue
        result = run_workspace_command(root_path, command, timeout_s=timeout_s, output_cap=output_cap)
        steps.append(
            _verify_step_result(
                name=name,
                label=label,
                required=True,
                status="executed",
                ok=bool(result.get("ok", False)),
                elapsed_ms=int(result.get("elapsed_ms") or 0),
                command=command,
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
                error="" if bool(result.get("ok", False)) else str(result.get("stderr") or result.get("stdout") or "").strip(),
            )
        )

    scorecard = build_coding_run_scorecard(root_path=root_path, health=health, steps=steps, benchmark_pack=benchmark_pack)
    return {
        "ok": bool(scorecard.get("status") != "red"),
        "workspace_root": str(root_path),
        "profile_key": profile_key,
        "health": health,
        "steps": steps,
        "benchmark_pack": benchmark_pack,
        "scorecard": scorecard,
        "next_actions": list(scorecard.get("next_actions") or []),
    }


def list_workspace_files(root_path: Path, *, limit: int = 50, recursive: bool = True) -> list[dict[str, Any]]:
    iterator = root_path.rglob("*") if recursive else root_path.glob("*")
    rows: list[dict[str, Any]] = []
    for path in iterator:
        if any(part in _IGNORE_PARTS for part in path.parts):
            continue
        if path.name == _WORKSPACE_MANIFEST:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "path": path.relative_to(root_path).as_posix(),
                "kind": "file" if path.is_file() else "dir",
                "size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            }
        )
    rows.sort(key=lambda item: (item["kind"] != "file", item["path"]))
    return rows[: max(1, min(int(limit or 50), 200))]


def read_workspace_text_file(root_path: Path, relative_path: str, *, max_chars: int = 12000) -> dict[str, Any]:
    target = resolve_workspace_path(root_path, relative_path, require_exists=True)
    if not target.is_file():
        raise ValueError(f"Target is not a file: {relative_path}")
    content = target.read_text(encoding="utf-8", errors="replace")
    cap = max(200, min(int(max_chars or 12000), 40000))
    truncated = len(content) > cap
    return {
        "path": target.relative_to(root_path).as_posix(),
        "content": content[:cap],
        "truncated": truncated,
        "chars": len(content),
    }


def write_workspace_text_file(
    root_path: Path,
    relative_path: str,
    content: str,
    *,
    mode: str = "overwrite",
    create_parents: bool = True,
    create_snapshot: bool = True,
    allow_large_write: bool = False,
    snapshot_label: str = "",
) -> dict[str, Any]:
    if len(str(content or "")) > _WRITE_CHAR_CAP:
        raise ValueError(f"Content exceeds cap of {_WRITE_CHAR_CAP} characters")
    target = resolve_workspace_path(root_path, relative_path, require_exists=False)
    if target.name == _WORKSPACE_MANIFEST:
        raise ValueError("Workspace manifest is protected")
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    normalized_mode = str(mode or "overwrite").strip().lower()
    if normalized_mode == "fail" and target.exists():
        raise FileExistsError(f"File already exists: {relative_path}")

    preview = preview_workspace_write(root_path, relative_path, str(content or ""), mode=normalized_mode)
    if bool(preview.get("requires_preview")) and not allow_large_write:
        raise ValueError("Large workspace writes require a preview/approval pass before execution")
    additional_files = 0 if target.exists() else 1
    incoming_bytes = len(str(content or "").encode("utf-8"))
    existing_bytes = target.stat().st_size if target.exists() else 0
    additional_bytes = incoming_bytes if normalized_mode == "append" else max(0, incoming_bytes - existing_bytes)
    quota = ensure_workspace_quota(root_path, additional_bytes=additional_bytes, additional_files=additional_files)

    snapshot_meta: dict[str, Any] = {}
    if create_snapshot and target.exists() and target.is_file():
        snapshot_meta = create_workspace_snapshot(
            root_path,
            label=snapshot_label or f"pre_write_{target.stem}",
        )

    file_mode = "a" if normalized_mode == "append" else "w"
    if file_mode == "a" and not target.exists():
        target.touch()
    with target.open(file_mode, encoding="utf-8") as handle:
        handle.write(str(content or ""))
    return {
        "path": target.relative_to(root_path).as_posix(),
        "bytes_written": len(str(content or "").encode("utf-8")),
        "exists": target.exists(),
        "preview": preview,
        "quota": quota,
        "snapshot": snapshot_meta,
    }


def make_workspace_directory(root_path: Path, relative_path: str, *, parents: bool = True, exist_ok: bool = True) -> dict[str, Any]:
    target = resolve_workspace_path(root_path, relative_path, require_exists=False)
    ensure_workspace_quota(root_path, additional_files=1)
    target.mkdir(parents=bool(parents), exist_ok=bool(exist_ok))
    return {
        "path": target.relative_to(root_path).as_posix(),
        "exists": target.exists(),
    }


def create_workspace_rollback(root_path: Path, *, label: str = "manual") -> dict[str, Any]:
    return create_workspace_snapshot(root_path, label=label)


def restore_workspace_rollback(root_path: Path, snapshot_id: str) -> dict[str, Any]:
    return restore_workspace_snapshot(root_path, snapshot_id)


def prepare_repo_snapshot_sandbox(
    source_root: str,
    *,
    user_id: str = "default_user",
    task_scope: str = "",
    output_root: str = "",
) -> dict[str, Any]:
    return prepare_repo_snapshot_workspace(
        source_root,
        user_id=user_id,
        task_scope=task_scope,
        output_root=output_root or CODING_SANDBOX_SNAPSHOT_ROOT,
    )


def run_command_in_workspace(
    root_path: Path,
    command: list[str],
    *,
    timeout_s: int = 30,
    output_cap: int = 20000,
    extra_env: dict[str, str] | None = None,
    backend_key: str = "",
) -> dict[str, Any]:
    started = time.monotonic()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
    }
    env.update({str(k): str(v) for k, v in dict(extra_env or {}).items()})
    quota = ensure_workspace_quota(root_path)
    selected_backend = str(backend_key or workspace_backend_key(root_path) or "managed_venv").strip().lower() or "managed_venv"
    backend_map = {row["key"]: row for row in list_coding_backends(root_path)}
    backend_meta = dict(backend_map.get(selected_backend) or backend_map.get("managed_venv") or {})
    execution_backend = str(backend_meta.get("execution_backend") or "local")
    try:
        result = DEFAULT_BACKEND_REGISTRY.get(execution_backend).execute(
            BackendExecutionRequest(
                commands=[[str(x) for x in list(command or [])]],
                cwd=str(root_path),
                env=env,
                timeout_seconds=max(1, min(int(timeout_s or 30), 120)),
                output_cap=output_cap,
                read_write_paths=[str(root_path)],
                read_only_paths=[],
                sandbox_root=str(root_path),
            )
        )
        return {
            "ok": int(result.returncode) == 0,
            "exit_code": int(result.returncode),
            "stdout": str(result.stdout or "")[:output_cap],
            "stderr": str(result.stderr or "")[:output_cap],
            "elapsed_ms": int(result.elapsed_ms),
            "backend": str(selected_backend),
            "execution_backend": str(result.backend),
            "quota": quota,
        }
    except ExecutionBackendError as exc:
        return {
            "ok": False,
            "exit_code": 125,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "backend": str(selected_backend),
            "execution_backend": execution_backend,
            "quota": quota,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": "",
            "stderr": f"Timed out after {timeout_s}s",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "backend": str(selected_backend),
            "execution_backend": execution_backend,
            "quota": quota,
        }
