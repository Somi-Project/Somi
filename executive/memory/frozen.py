from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FrozenMemoryStore:
    def __init__(self, root_dir: str | Path = "sessions/state/memory_blocks") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(user_id or "default_user"))[:100] or "default_user"
        return self.root_dir / f"{safe}.json"

    def write_snapshot(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(payload or {})
        snapshot["user_id"] = str(user_id or "default_user")
        snapshot["updated_at"] = _now_iso()
        path = self._path(user_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return snapshot

    def read_snapshot(self, user_id: str) -> dict[str, Any] | None:
        path = self._path(user_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None
