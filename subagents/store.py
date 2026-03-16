from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_run_id(run_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(run_id or "").strip())[:120] or "subagent"


class SubagentStatusStore:
    def __init__(self, root_dir: str | Path = "sessions/subagents") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        return self.root_dir / f"{_safe_run_id(run_id)}.json"

    def write_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        payload = dict(snapshot or {})
        payload.setdefault("updated_at", _now_iso())
        path = self.path_for(str(payload.get("run_id") or "subagent"))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return payload

    def load_snapshot(self, run_id: str) -> dict[str, Any] | None:
        path = self.path_for(run_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def list_snapshots(
        self,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        wanted = {str(x or "").strip().lower() for x in list(statuses or []) if str(x or "").strip()}
        out: list[dict[str, Any]] = []
        for path in sorted(self.root_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            if user_id and str(raw.get("user_id") or "") != str(user_id):
                continue
            if thread_id and str(raw.get("thread_id") or "") != str(thread_id):
                continue
            if wanted and str(raw.get("status") or "").strip().lower() not in wanted:
                continue
            out.append(raw)
        out.sort(key=lambda row: str(row.get("updated_at") or row.get("started_at") or ""), reverse=True)
        return out[: max(1, int(limit or 20))]
