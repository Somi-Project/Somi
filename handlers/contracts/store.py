from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ArtifactStore:
    def __init__(self, root_dir: str = "sessions/artifacts"):
        self.root_dir = root_dir
        self._lock = threading.Lock()
        os.makedirs(self.root_dir, exist_ok=True)

    def _safe_session_id(self, session_id: str) -> str:
        sid = str(session_id or "default_user").strip() or "default_user"
        sid = re.sub(r"[^a-zA-Z0-9._-]", "_", sid)
        return sid[:120]

    def _path(self, session_id: str) -> str:
        sid = self._safe_session_id(session_id)
        return os.path.join(self.root_dir, f"{sid}.jsonl")

    def append(self, session_id: str, artifact: Dict[str, Any]) -> None:
        path = self._path(session_id)
        sid = self._safe_session_id(session_id)
        payload = dict(artifact or {})
        payload.setdefault("session_id", sid)
        created_at = str(payload.get("created_at") or "").strip()
        if not payload.get("timestamp"):
            payload["timestamp"] = created_at or datetime.now(timezone.utc).isoformat()
        payload.setdefault("artifact_id", f"adhoc_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def get_last_by_type(self, session_id: str, artifact_type: str) -> Optional[Dict[str, Any]]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return None
        last = None
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if str(item.get("artifact_type")) == str(artifact_type):
                        last = item
        return last

    def get_by_id(self, session_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return None
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if str(item.get("artifact_id")) == str(artifact_id):
                        return item
        return None
