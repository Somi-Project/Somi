from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from workflow_runtime import WorkflowManifestStore, WorkflowRunStore


def _safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip().lower())[:100] or "skill"


class SkillSuggestionEngine:
    def __init__(
        self,
        *,
        workflow_store: WorkflowRunStore | None = None,
        manifest_store: WorkflowManifestStore | None = None,
        output_path: str | Path = "sessions/evals/skill_suggestions.json",
    ) -> None:
        self.workflow_store = workflow_store or WorkflowRunStore()
        self.manifest_store = manifest_store or WorkflowManifestStore()
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def generate(self, *, user_id: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self.workflow_store.list_snapshots(user_id=user_id, limit=max(12, int(limit or 8) * 2)):
            status = str(row.get("status") or "").strip().lower()
            if status not in {"completed", "ok", "success"}:
                continue
            manifest_id = str(row.get("manifest_id") or "").strip()
            manifest = self.manifest_store.load(manifest_id) if manifest_id else None
            key = manifest_id or str(row.get("run_id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            name = str(row.get("manifest_name") or getattr(manifest, "name", "") or key)
            summary = str(row.get("summary") or row.get("thread_id") or "successful workflow")
            allowed_tools = list(getattr(manifest, "allowed_tools", tuple()) or row.get("allowed_tools") or [])
            suggestion = {
                "skill_id": f"{_safe_id(name)}_skill",
                "title": f"{name} Skill",
                "source_run_id": str(row.get("run_id") or ""),
                "source_manifest_id": manifest_id,
                "why": summary,
                "recommended_tools": allowed_tools,
                "template_markdown": "\n".join(
                    [
                        f"# {name} Skill",
                        "",
                        f"Use when: {summary}",
                        f"Preferred tools: {', '.join(allowed_tools) if allowed_tools else 'workflow runtime'}",
                        "Outcome: convert a successful workflow into a reusable operator pattern.",
                    ]
                ),
            }
            suggestions.append(suggestion)
            if len(suggestions) >= max(1, int(limit or 8)):
                break

        self.output_path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return suggestions
