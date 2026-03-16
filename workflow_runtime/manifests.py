from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _safe_id(value: Any, *, fallback: str = "workflow") -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value or "").strip().lower())[:80]
    return text or fallback


def _dedupe(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(items or []):
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


@dataclass(frozen=True)
class WorkflowManifest:
    manifest_id: str
    name: str
    script: str
    allowed_tools: tuple[str, ...]
    description: str = ""
    backend: str = "local"
    timeout_seconds: int = 60
    max_tool_calls: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": str(self.manifest_id),
            "name": str(self.name),
            "description": str(self.description),
            "script": str(self.script),
            "allowed_tools": list(self.allowed_tools),
            "backend": str(self.backend),
            "timeout_seconds": int(self.timeout_seconds),
            "max_tool_calls": int(self.max_tool_calls),
            "metadata": dict(self.metadata or {}),
        }


def normalize_manifest(payload: dict[str, Any]) -> WorkflowManifest:
    raw = dict(payload or {})
    manifest_id = _safe_id(raw.get("manifest_id") or raw.get("name") or "workflow")
    name = str(raw.get("name") or manifest_id).strip() or manifest_id
    script = str(raw.get("script") or "")
    allowed_tools = tuple(_dedupe(list(raw.get("allowed_tools") or [])))
    return WorkflowManifest(
        manifest_id=manifest_id,
        name=name,
        description=str(raw.get("description") or "").strip(),
        script=script,
        allowed_tools=allowed_tools,
        backend=str(raw.get("backend") or "local").strip().lower() or "local",
        timeout_seconds=max(5, min(int(raw.get("timeout_seconds") or 60), 900)),
        max_tool_calls=max(1, min(int(raw.get("max_tool_calls") or 8), 100)),
        metadata=dict(raw.get("metadata") or {}),
    )


class WorkflowManifestStore:
    def __init__(self, root_dir: str | Path = "workflow_runtime/manifests") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, manifest_id: str) -> Path:
        return self.root_dir / f"{_safe_id(manifest_id)}.json"

    def save(self, manifest: WorkflowManifest | dict[str, Any]) -> WorkflowManifest:
        item = normalize_manifest(manifest.to_dict() if isinstance(manifest, WorkflowManifest) else manifest)
        path = self.path_for(item.manifest_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(item.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return item

    def load(self, manifest_id: str) -> WorkflowManifest | None:
        path = self.path_for(manifest_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        return normalize_manifest(raw)

    def list_manifests(self) -> list[WorkflowManifest]:
        out: list[WorkflowManifest] = []
        for path in sorted(self.root_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            out.append(normalize_manifest(raw))
        return sorted(out, key=lambda item: item.manifest_id)
