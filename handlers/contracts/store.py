from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

from handlers.contracts.base import normalize_envelope


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

    def _index_path(self, session_id: str) -> str:
        sid = self._safe_session_id(session_id)
        return os.path.join(self.root_dir, f"{sid}.index.json")

    def _lock_path(self, session_id: str) -> str:
        sid = self._safe_session_id(session_id)
        return os.path.join(self.root_dir, f"{sid}.lock")

    @contextmanager
    def _session_file_lock(self, session_id: str):
        lock_path = self._lock_path(session_id)
        fd = None
        try:
            fd = open(lock_path, "a+", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fd is not None:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                finally:
                    fd.close()

    def _redact_value(self, value: Any) -> tuple[Any, bool]:
        redacted = False
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                rv, rr = self._redact_value(v)
                out[k] = rv
                redacted = redacted or rr
            return out, redacted
        if isinstance(value, list):
            out = []
            for v in value:
                rv, rr = self._redact_value(v)
                out.append(rv)
                redacted = redacted or rr
            return out, redacted
        text = str(value)
        patterns = [r"sk-[A-Za-z0-9_-]{12,}", r"ghp_[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._\-]{16,}", r"-----BEGIN PRIVATE KEY-----[\s\S]+?-----END PRIVATE KEY-----", r"\b[A-Za-z0-9_\-]{40,}\b"]
        out = text
        for p in patterns:
            out2 = re.sub(p, "[REDACTED]", out, flags=re.IGNORECASE)
            if out2 != out:
                redacted = True
            out = out2
        if not isinstance(value, str):
            return (out if redacted else value), redacted
        return out, redacted

    def append(self, session_id: str, artifact: Dict[str, Any]) -> None:
        sid = self._safe_session_id(session_id)
        path = self._path(sid)
        payload = normalize_envelope(dict(artifact or {}), session_id=sid)
        payload, was_redacted = self._redact_value(payload)
        if was_redacted:
            warns = list(payload.get("warnings") or [])
            warns.append("Potential secret redacted")
            payload["warnings"] = warns

        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self._session_file_lock(sid):
                with open(path, "a", encoding="utf-8") as f:
                    offset = f.tell()
                    f.write(line + "\n")
                    f.flush()
                self._update_index(sid, payload, offset)

    def _update_index(self, session_id: str, artifact: Dict[str, Any], offset: int) -> None:
        idx_path = self._index_path(session_id)
        idx = {"session_id": session_id, "contracts": {}, "by_id": {}}
        if os.path.exists(idx_path):
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    idx = json.loads(f.read())
            except Exception:
                idx = {"session_id": session_id, "contracts": {}, "by_id": {}}
        cid = str(artifact.get("contract_name") or "")
        aid = str(artifact.get("artifact_id") or "")
        if cid:
            idx.setdefault("contracts", {})[cid] = {"artifact_id": aid, "timestamp": artifact.get("timestamp")}
        if aid:
            idx.setdefault("by_id", {})[aid] = {"contract_name": cid, "offset": offset, "timestamp": artifact.get("timestamp")}
        tmp = idx_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        os.replace(tmp, idx_path)

    def _iter_jsonl(self, session_id: str):
        path = self._path(session_id)
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield normalize_envelope(json.loads(line), session_id=session_id)
                except Exception:
                    continue

    def _rebuild_index(self, session_id: str) -> None:
        path = self._path(session_id)
        idx_path = self._index_path(session_id)
        if not os.path.exists(path):
            if os.path.exists(idx_path):
                os.remove(idx_path)
            return
        idx = {"session_id": session_id, "contracts": {}, "by_id": {}}
        with open(path, "r", encoding="utf-8") as f:
            while True:
                offset = f.tell()
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    item = normalize_envelope(json.loads(line), session_id=session_id)
                except Exception:
                    continue
                cid = str(item.get("contract_name") or "")
                aid = str(item.get("artifact_id") or "")
                if cid:
                    idx.setdefault("contracts", {})[cid] = {"artifact_id": aid, "timestamp": item.get("timestamp")}
                if aid:
                    idx.setdefault("by_id", {})[aid] = {"contract_name": cid, "offset": offset, "timestamp": item.get("timestamp")}
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)

    def get_last(self, session_id: str, contract_name: str) -> Optional[Dict[str, Any]]:
        sid = self._safe_session_id(session_id)
        idx_path = self._index_path(sid)
        aid = None
        if os.path.exists(idx_path):
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    idx = json.loads(f.read())
                aid = ((idx.get("contracts") or {}).get(contract_name) or {}).get("artifact_id")
            except Exception:
                self._rebuild_index(sid)
                return self.get_last(sid, contract_name)
        if aid:
            return self.get_by_id(sid, aid)
        return self.get_last_by_type(sid, contract_name)

    def get_last_by_type(self, session_id: str, artifact_type: str) -> Optional[Dict[str, Any]]:
        last = None
        for item in self._iter_jsonl(self._safe_session_id(session_id)):
            item_type = str(item.get("artifact_type") or item.get("contract_name") or "")
            if item_type == str(artifact_type):
                last = item
        return last

    def get_by_id(self, session_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        sid = self._safe_session_id(session_id)
        idx_path = self._index_path(sid)
        if os.path.exists(idx_path):
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    idx = json.loads(f.read())
                rec = (idx.get("by_id") or {}).get(str(artifact_id))
                if rec and rec.get("offset") is not None:
                    with open(self._path(sid), "r", encoding="utf-8") as f:
                        f.seek(int(rec.get("offset")))
                        line = f.readline().strip()
                        if line:
                            return normalize_envelope(json.loads(line), session_id=sid)
            except Exception:
                self._rebuild_index(sid)
        for item in self._iter_jsonl(sid):
            if str(item.get("artifact_id")) == str(artifact_id):
                return item
        return None
