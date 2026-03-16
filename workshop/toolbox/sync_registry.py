from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.hashing import sha256_file
from workshop.toolbox.registry import ToolRegistry


def _hash_tree(root: Path) -> dict[str, str]:
    ignore_dirs = {"__pycache__", ".pytest_cache", ".sandbox_home"}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in ignore_dirs for part in p.parts):
            continue
        if p.suffix.lower() in {".pyc", ".pyo"}:
            continue
        rel = p.relative_to(root).as_posix()
        out[rel] = sha256_file(p)
    return out


def _entry_from_manifest(tool_root: Path) -> dict[str, Any] | None:
    manifest_path = tool_root / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not name or not version:
        return None

    return {
        "name": name,
        "version": version,
        "path": str(tool_root.as_posix()),
        "description": str(manifest.get("description") or ""),
        "display_name": str(manifest.get("display_name") or manifest.get("name") or name),
        "hashes": _hash_tree(tool_root),
        "enabled": True,
        "aliases": list(manifest.get("aliases") or []),
        "examples": list(manifest.get("examples") or []),
        "tags": list(manifest.get("tags") or []),
        "capabilities": list(manifest.get("capabilities") or []),
        "toolsets": list(manifest.get("toolsets") or []),
        "channels": list(manifest.get("channels") or []),
        "backends": list(manifest.get("backends") or []),
        "runtime": dict(manifest.get("runtime") or {}),
        "exposure": dict(manifest.get("exposure") or {}),
        "input_schema": dict(manifest.get("input_schema") or {}),
        "policy": dict(manifest.get("policy") or {}),
    }


def sync_installed_tools(installed_root: str = "workshop/tools/installed", registry_path: str = "workshop/tools/registry.json") -> dict[str, Any]:
    root = Path(installed_root)
    registry = ToolRegistry(path=registry_path)
    added = 0
    scanned = 0

    if not root.exists():
        return {"ok": True, "scanned": 0, "registered": 0}

    for tool_name_dir in sorted(root.iterdir()):
        if not tool_name_dir.is_dir():
            continue
        for version_dir in sorted(tool_name_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            scanned += 1
            entry = _entry_from_manifest(version_dir)
            if not entry:
                continue
            registry.register(entry)
            added += 1

    return {"ok": True, "scanned": scanned, "registered": added}
