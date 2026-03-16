from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.hashing import sha256_file
from workshop.toolbox.registry import ToolRegistry
from workshop.toolbox.runtime import InternalToolRuntime


def _check_hashes(path: Path, expected: dict[str, str]) -> list[str]:
    issues: list[str] = []
    for rel, want in sorted((expected or {}).items()):
        fp = path / rel
        if not fp.exists():
            issues.append(f"missing file: {rel}")
            continue
        if not fp.is_file():
            issues.append(f"not a file: {rel}")
            continue
        got = sha256_file(fp)
        if str(got) != str(want):
            issues.append(f"hash mismatch: {rel}")
    return issues


def generate_tool_health_report(registry_path: str = "workshop/tools/registry.json") -> dict[str, Any]:
    registry = ToolRegistry(path=registry_path)
    runtime = InternalToolRuntime(registry=registry)

    rows: list[dict[str, Any]] = []
    unhealthy = 0

    for entry in registry.list_tools():
        name = str(entry.get("name") or "")
        version = str(entry.get("version") or "")
        path = Path(str(entry.get("path") or ""))
        issues: list[str] = []

        if not path.exists() or not path.is_dir():
            issues.append("missing tool directory")
        else:
            tool_py = path / "tool.py"
            manifest = path / "manifest.json"
            if not tool_py.exists():
                issues.append("missing tool.py")
            if not manifest.exists():
                issues.append("missing manifest.json")
            else:
                try:
                    meta = json.loads(manifest.read_text(encoding="utf-8"))
                    if str(meta.get("name") or "") and str(meta.get("name")) != name:
                        issues.append("manifest name mismatch")
                    if str(meta.get("version") or "") and str(meta.get("version")) != version:
                        issues.append("manifest version mismatch")
                except Exception as exc:
                    issues.append(f"manifest parse failed: {exc}")

            issues.extend(_check_hashes(path, dict(entry.get("hashes") or {})))

        try:
            runtime._load_module(f"{name}@{version}")
        except Exception as exc:
            issues.append(f"module load failed: {exc}")

        healthy = not issues
        if not healthy:
            unhealthy += 1

        rows.append(
            {
                "name": name,
                "version": version,
                "path": str(path),
                "healthy": healthy,
                "issues": issues,
            }
        )

    return {
        "ok": True,
        "total": len(rows),
        "healthy": len(rows) - unhealthy,
        "unhealthy": unhealthy,
        "tools": rows,
    }
