from __future__ import annotations

from functools import lru_cache
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _command_path(command: str) -> str:
    return shutil.which(command) or ""


def _workspace_executable(workspace: Path | None, *relative_parts: str) -> str:
    if workspace is None:
        return ""
    candidate = workspace.joinpath(*relative_parts)
    return str(candidate) if candidate.exists() else ""


def _version_probe(command: str, path: str) -> list[str]:
    if path.lower().endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path, "--version"]
    if path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path, "--version"]
    if command in {"npm", "npx", "pnpm"}:
        return ["cmd", "/c", command, "--version"]
    return [path or command, "--version"]


def _detect_version(command: str, path: str) -> str:
    if not path and command != "python":
        return ""
    try:
        started = time.monotonic()
        proc = subprocess.run(
            _version_probe(command, path),
            capture_output=True,
            text=True,
            timeout=2,
            shell=False,
        )
        if proc.returncode != 0:
            return ""
        text = str(proc.stdout or proc.stderr or "").strip().splitlines()
        if not text or time.monotonic() - started > 2.5:
            return ""
        return text[0].strip()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def _global_runtime_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []

    def _add_runtime(key: str, command: str, *, label: str = "", explicit_path: str = "") -> None:
        resolved = explicit_path or _command_path(command) or ""
        rows.append(
            {
                "key": key,
                "label": label or key.title(),
                "command": command,
                "path": resolved,
                "available": bool(resolved),
                "version": _detect_version(command, resolved) if resolved else "",
            }
        )

    _add_runtime("python", "python", label="Python", explicit_path=sys.executable)
    _add_runtime("pytest", "pytest", label="pytest")
    _add_runtime("pip", "pip", label="pip")
    _add_runtime("uv", "uv", label="uv")
    _add_runtime("node", "node", label="Node.js")
    _add_runtime("npm", "npm", label="npm")
    _add_runtime("npx", "npx", label="npx")
    _add_runtime("pnpm", "pnpm", label="pnpm")
    _add_runtime("bun", "bun", label="bun")
    _add_runtime("tsc", "tsc", label="TypeScript Compiler")
    _add_runtime("git", "git", label="Git")
    return tuple(rows)


def _workspace_markers(workspace: Path | None) -> list[dict[str, Any]]:
    if workspace is None:
        return []
    marker_specs = (
        ("pyproject.toml", "python_project"),
        ("requirements.txt", "python_requirements"),
        ("package.json", "node_project"),
        ("tsconfig.json", "typescript_config"),
        ("index.html", "web_entry"),
    )
    markers: list[dict[str, Any]] = []
    for relative_path, label in marker_specs:
        candidate = workspace / relative_path
        if candidate.exists():
            markers.append({"path": relative_path, "label": label})
    return markers


def build_runtime_inventory(*, workspace_root: str = "", refresh: bool = False) -> dict[str, Any]:
    if refresh:
        _global_runtime_rows.cache_clear()
    runtimes = [dict(row) for row in _global_runtime_rows()]
    workspace = Path(str(workspace_root or "")).expanduser().resolve() if workspace_root else None

    venv_python = ""
    venv_pytest = ""
    workspace_tsc = ""
    if workspace:
        venv_python = (
            _workspace_executable(workspace, ".venv", "Scripts", "python.exe")
            or _workspace_executable(workspace, ".venv", "bin", "python")
        )
        venv_pytest = (
            _workspace_executable(workspace, ".venv", "Scripts", "pytest.exe")
            or _workspace_executable(workspace, ".venv", "bin", "pytest")
        )
        workspace_tsc = (
            _workspace_executable(workspace, "node_modules", ".bin", "tsc.cmd")
            or _workspace_executable(workspace, "node_modules", ".bin", "tsc")
        )
    runtimes.append(
        {
            "key": "workspace_python",
            "label": "Workspace Python",
            "command": "python",
            "path": venv_python,
            "available": bool(venv_python),
            "version": _detect_version("python", venv_python) if venv_python else "",
        }
    )
    runtimes.append(
        {
            "key": "workspace_pytest",
            "label": "Workspace pytest",
            "command": "pytest",
            "path": venv_pytest,
            "available": bool(venv_pytest),
            "version": _detect_version("pytest", venv_pytest) if venv_pytest else "",
        }
    )
    runtimes.append(
        {
            "key": "workspace_tsc",
            "label": "Workspace TypeScript Compiler",
            "command": "tsc",
            "path": workspace_tsc,
            "available": bool(workspace_tsc),
            "version": _detect_version("tsc", workspace_tsc) if workspace_tsc else "",
        }
    )
    return {
        "runtimes": runtimes,
        "available_keys": [row["key"] for row in runtimes if bool(row.get("available"))],
        "workspace_markers": _workspace_markers(workspace),
    }
