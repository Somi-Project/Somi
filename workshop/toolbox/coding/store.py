from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workshop.toolbox.coding.models import CodingSessionSnapshot


class CodingSessionStore:
    def __init__(self, root_dir: str | Path = "sessions/coding") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.root_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir = self.root_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        safe = str(session_id or "").strip() or "session"
        return self.sessions_dir / f"{safe}.json"

    def _active_path(self, user_id: str) -> Path:
        safe = str(user_id or "default_user").strip() or "default_user"
        return self.users_dir / safe / "active_session.json"

    def write_session(self, session: CodingSessionSnapshot | dict[str, Any]) -> dict[str, Any]:
        snapshot = session if isinstance(session, CodingSessionSnapshot) else CodingSessionSnapshot.from_dict(dict(session or {}))
        payload = snapshot.to_dict()
        path = self._session_path(snapshot.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if str(snapshot.status).lower() == "active":
            active_path = self._active_path(snapshot.user_id)
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(json.dumps({"session_id": snapshot.session_id}, indent=2) + "\n", encoding="utf-8")
        return payload

    def update_session(
        self,
        session_id: str,
        *,
        patch: dict[str, Any] | None = None,
        workspace_patch: dict[str, Any] | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        session = self.load_session(session_id)
        if not isinstance(session, dict):
            return None
        payload = dict(session)
        if patch:
            payload.update(dict(patch))
        if workspace_patch:
            payload["workspace"] = {**dict(payload.get("workspace") or {}), **dict(workspace_patch)}
        if metadata_patch:
            payload["metadata"] = {**dict(payload.get("metadata") or {}), **dict(metadata_patch)}
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self.write_session(payload)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def get_active_session(self, user_id: str) -> dict[str, Any] | None:
        active_path = self._active_path(user_id)
        if not active_path.exists():
            return None
        try:
            payload = json.loads(active_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        session_id = str(dict(payload or {}).get("session_id") or "").strip()
        if not session_id:
            return None
        return self.load_session(session_id)

    def list_sessions(self, *, user_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.sessions_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if user_id and str(payload.get("user_id") or "").strip() != str(user_id).strip():
                continue
            rows.append(payload)
        rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit or 20))]
