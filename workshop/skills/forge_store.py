from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillForgeStore:
    def __init__(self, root_dir: str | Path = "sessions/skills/forge", drafts_dir: str | Path = "sessions/skills/forge/workspace") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir = self.root_dir / "records"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir = Path(drafts_dir)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.gap_path = self.root_dir / "gap_signals.json"

    def _record_path(self, draft_id: str) -> Path:
        return self.records_dir / f"{str(draft_id or '').strip()}.json"

    def write_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        draft = dict(payload or {})
        draft.setdefault("updated_at", _now_iso())
        path = self._record_path(str(draft.get("draft_id") or ""))
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return draft

    def load_draft(self, draft_id: str) -> dict[str, Any] | None:
        path = self._record_path(draft_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def list_drafts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit or 20))]

    def _load_gap_signals(self) -> dict[str, Any]:
        if not self.gap_path.exists():
            return {"items": {}}
        try:
            payload = json.loads(self.gap_path.read_text(encoding="utf-8"))
        except Exception:
            return {"items": {}}
        if not isinstance(payload, dict):
            return {"items": {}}
        payload.setdefault("items", {})
        return payload

    def _save_gap_signals(self, payload: dict[str, Any]) -> None:
        self.gap_path.write_text(json.dumps(dict(payload or {}), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def record_gap_signal(self, *, user_id: str, capability: str, prompt: str, source: str) -> dict[str, Any]:
        safe_user = str(user_id or "default_user").strip() or "default_user"
        safe_capability = str(capability or "general").strip().lower() or "general"
        payload = self._load_gap_signals()
        items = dict(payload.get("items") or {})
        key = f"{safe_user}:{safe_capability}"
        row = dict(items.get(key) or {})
        prompts = [str(item) for item in list(row.get("recent_prompts") or []) if str(item).strip()]
        if prompt:
            prompts.append(str(prompt))
        row.update(
            {
                "user_id": safe_user,
                "capability": safe_capability,
                "count": int(row.get("count") or 0) + 1,
                "source": str(source or "chat"),
                "last_prompt": str(prompt or ""),
                "recent_prompts": prompts[-5:],
                "updated_at": _now_iso(),
            }
        )
        items[key] = row
        payload["items"] = items
        self._save_gap_signals(payload)
        return row
