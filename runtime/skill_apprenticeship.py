from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from learning.skills import SkillSuggestionEngine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_objective(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\b(?:please|can you|help me|i need to|could you|would you)\b", " ", text)
    text = re.sub(r"\b(?:in the background|for me|right now|today)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160]


def _suggestion_id(seed: str) -> str:
    digest = hashlib.sha256(str(seed or "").encode("utf-8", errors="ignore")).hexdigest()
    return f"apprentice_{digest[:12]}"


class SkillApprenticeshipLedger:
    def __init__(
        self,
        *,
        root_dir: str | Path = "sessions/autonomy/skill_apprenticeship",
        workflow_suggester: "SkillSuggestionEngine | Any | None" = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.activities_path = self.root_dir / "activities.jsonl"
        self.suggestions_path = self.root_dir / "suggestions.json"
        if workflow_suggester is None:
            from learning.skills import SkillSuggestionEngine

            workflow_suggester = SkillSuggestionEngine(output_path=self.root_dir / "workflow_seed_suggestions.json")
        self.workflow_suggester = workflow_suggester

    def record_activity(
        self,
        *,
        user_id: str,
        objective: str,
        kind: str,
        surface: str,
        success: bool,
        tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "created_at": _now_iso(),
            "user_id": str(user_id or "default_user"),
            "objective": _safe_text(objective, limit=260),
            "objective_key": _normalize_objective(objective),
            "kind": str(kind or "task").strip().lower() or "task",
            "surface": str(surface or "gui").strip().lower() or "gui",
            "success": bool(success),
            "tools": [str(item) for item in list(tools or []) if str(item).strip()][:10],
            "metadata": dict(metadata or {}),
        }
        with self.activities_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def list_activities(self, *, user_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.activities_path.exists():
            return rows
        with self.activities_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                if user_id and str(payload.get("user_id") or "") != str(user_id):
                    continue
                rows.append(payload)
        return rows[-max(1, int(limit or 80)) :]

    def build_suggestions(self, *, user_id: str | None = None, limit: int = 6) -> list[dict[str, Any]]:
        activities = self.list_activities(user_id=user_id, limit=240)
        grouped: dict[str, dict[str, Any]] = {}
        for row in activities:
            key = str(row.get("objective_key") or "").strip()
            objective = str(row.get("objective") or "").strip()
            if not key or not objective:
                continue
            bucket = grouped.setdefault(
                key,
                {
                    "objective": objective,
                    "count": 0,
                    "success_count": 0,
                    "surfaces": set(),
                    "tools": set(),
                    "last_seen_at": "",
                },
            )
            bucket["count"] += 1
            bucket["success_count"] += 1 if bool(row.get("success")) else 0
            bucket["surfaces"].add(str(row.get("surface") or "gui"))
            bucket["tools"].update(str(item) for item in list(row.get("tools") or []) if str(item).strip())
            bucket["last_seen_at"] = str(row.get("created_at") or bucket.get("last_seen_at") or "")

        suggestions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key, bucket in sorted(
            grouped.items(),
            key=lambda item: (
                -int(dict(item[1]).get("count") or 0),
                -int(dict(item[1]).get("success_count") or 0),
                str(dict(item[1]).get("last_seen_at") or ""),
            ),
        ):
            count = int(bucket.get("count") or 0)
            if count < 2:
                continue
            title_seed = str(bucket.get("objective") or "Workflow").strip().rstrip(".")
            suggestion_id = _suggestion_id(key)
            if suggestion_id in seen:
                continue
            seen.add(suggestion_id)
            suggestions.append(
                {
                    "suggestion_id": suggestion_id,
                    "kind": "workflow_repetition",
                    "title": f"{title_seed[:64]} Skill Draft",
                    "why": f"This workflow appeared {count} times and succeeded {int(bucket.get('success_count') or 0)} times.",
                    "objective": title_seed,
                    "approval_required": True,
                    "draft_ready": count >= 3,
                    "recommended_tools": sorted(bucket.get("tools") or []),
                    "surfaces": sorted(bucket.get("surfaces") or []),
                    "count": count,
                    "next_step": "Review and approve a draft skill before enabling it.",
                }
            )
            if len(suggestions) >= max(1, int(limit or 6)):
                break

        external = self.workflow_suggester.generate(user_id=user_id, limit=max(1, int(limit or 6)))
        for row in external:
            suggestion_id = _suggestion_id(str(row.get("skill_id") or row.get("title") or "workflow"))
            if suggestion_id in seen:
                continue
            seen.add(suggestion_id)
            suggestions.append(
                {
                    "suggestion_id": suggestion_id,
                    "kind": "workflow_success",
                    "title": str(row.get("title") or "Workflow Skill"),
                    "why": str(row.get("why") or "Successful workflow can become a reusable skill."),
                    "objective": str(row.get("title") or row.get("skill_id") or "workflow"),
                    "approval_required": True,
                    "draft_ready": True,
                    "recommended_tools": [str(item) for item in list(row.get("recommended_tools") or []) if str(item).strip()],
                    "surfaces": [],
                    "count": 1,
                    "next_step": "Review and approve this workflow-derived skill draft before installing it.",
                }
            )
            if len(suggestions) >= max(1, int(limit or 6)):
                break

        self.suggestions_path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return suggestions[: max(1, int(limit or 6))]

    def snapshot(self, *, user_id: str | None = None, limit: int = 6) -> dict[str, Any]:
        suggestions = self.build_suggestions(user_id=user_id, limit=limit)
        return {
            "recent_activities": self.list_activities(user_id=user_id, limit=12),
            "suggestions": suggestions,
            "approval_required_count": sum(1 for row in suggestions if bool(row.get("approval_required"))),
            "draft_ready_count": sum(1 for row in suggestions if bool(row.get("draft_ready"))),
            "updated_at": _now_iso(),
        }
