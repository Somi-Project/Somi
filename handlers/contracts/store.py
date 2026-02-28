from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

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

    def _global_index_dir(self) -> str:
        p = os.path.join(self.root_dir, "index")
        os.makedirs(p, exist_ok=True)
        return p

    def _thread_index_path(self) -> str:
        return os.path.join(self._global_index_dir(), "thread_index.json")

    def _tag_index_path(self) -> str:
        return os.path.join(self._global_index_dir(), "tag_index.json")

    def _status_index_path(self) -> str:
        return os.path.join(self._global_index_dir(), "status_index.json")

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
                self._update_global_indexes(sid, payload)

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


    def _minimal_meta(self, session_id: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(artifact.get("data") or artifact.get("content") or {})
        title = data.get("title") or data.get("objective") or data.get("question") or data.get("thread_id") or artifact.get("artifact_type")
        return {
            "artifact_id": str(artifact.get("artifact_id") or ""),
            "session_id": session_id,
            "thread_id": artifact.get("thread_id"),
            "type": str(artifact.get("artifact_type") or artifact.get("contract_name") or ""),
            "title": str(title or "")[:200],
            "updated_at": artifact.get("timestamp"),
            "status": str(artifact.get("status") or "unknown"),
            "tags": [str(x) for x in list(artifact.get("tags") or [])][:20],
        }

    def _read_json(self, path: str, default: Dict[str, Any]) -> Dict[str, Any]:
        if not os.path.exists(path):
            return dict(default)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except Exception:
            return dict(default)

    def _write_json_atomic(self, path: str, payload: Dict[str, Any]) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _append_unique(self, rows: List[Dict[str, Any]], item: Dict[str, Any], *, max_items: int = 200) -> List[Dict[str, Any]]:
        aid = str(item.get("artifact_id") or "")
        out = [r for r in rows if str(r.get("artifact_id") or "") != aid]
        out.insert(0, item)
        return out[:max_items]

    def _update_global_indexes(self, session_id: str, artifact: Dict[str, Any]) -> None:
        item = self._minimal_meta(session_id, artifact)
        if not item.get("artifact_id"):
            return

        thread_idx = self._read_json(self._thread_index_path(), {"by_thread_id": {}, "recent_open_threads": []})
        tid = str(item.get("thread_id") or "").strip()
        if tid:
            rows = list(((thread_idx.get("by_thread_id") or {}).get(tid) or []))
            thread_idx.setdefault("by_thread_id", {})[tid] = self._append_unique(rows, item, max_items=200)
        if item.get("status") in {"open", "in_progress", "blocked"}:
            thread_idx["recent_open_threads"] = self._append_unique(list(thread_idx.get("recent_open_threads") or []), item, max_items=300)
        else:
            thread_idx["recent_open_threads"] = [r for r in list(thread_idx.get("recent_open_threads") or []) if str(r.get("artifact_id")) != item["artifact_id"]][:300]
        self._write_json_atomic(self._thread_index_path(), thread_idx)

        tag_idx = self._read_json(self._tag_index_path(), {"by_tag": {}})
        for tag in list(item.get("tags") or [])[:20]:
            key = str(tag or "").strip().lower()
            if not key:
                continue
            rows = list(((tag_idx.get("by_tag") or {}).get(key) or []))
            tag_idx.setdefault("by_tag", {})[key] = self._append_unique(rows, item, max_items=200)
        self._write_json_atomic(self._tag_index_path(), tag_idx)

        status_idx = self._read_json(self._status_index_path(), {"by_status": {}})
        st = str(item.get("status") or "unknown")
        rows = list(((status_idx.get("by_status") or {}).get(st) or []))
        status_idx.setdefault("by_status", {})[st] = self._append_unique(rows, item, max_items=300)
        self._write_json_atomic(self._status_index_path(), status_idx)


    def _compact_rows_by_age(self, rows: List[Dict[str, Any]], *, max_age_days: int, max_items: int) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(max_age_days)))
        out: List[Dict[str, Any]] = []
        for row in list(rows or []):
            ts = str((row or {}).get("updated_at") or "").strip()
            keep = True
            if ts:
                try:
                    if ts.endswith("Z"):
                        ts = ts[:-1] + "+00:00"
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        keep = False
                except Exception:
                    keep = True
            if keep:
                out.append(dict(row))
            if len(out) >= max_items:
                break
        return out


    def _status_age_limit_days(self, status: str, base_days: int, *, adaptive: bool) -> int:
        if not adaptive:
            return max(1, int(base_days))
        s = str(status or "unknown")
        if s in {"open", "in_progress"}:
            return max(int(base_days), 365)
        if s in {"blocked"}:
            return max(int(base_days), 270)
        if s in {"done", "unknown"}:
            return min(int(base_days), 120)
        return max(1, int(base_days))

    def _adaptive_age_days_for_rows(self, rows: List[Dict[str, Any]], base_days: int, *, adaptive: bool) -> int:
        if not adaptive:
            return max(1, int(base_days))
        n = len(list(rows or []))
        if n >= 120:
            return min(540, int(base_days) * 2)
        if n >= 60:
            return min(365, int(base_days) + 90)
        return max(1, int(base_days))


    def _age_days_with_status_mix(self, rows: List[Dict[str, Any]], base_days: int, *, adaptive: bool) -> int:
        age_days = self._adaptive_age_days_for_rows(rows, base_days, adaptive=adaptive)
        if not adaptive:
            return age_days
        statuses = {str((r or {}).get("status") or "unknown") for r in list(rows or [])}
        for st in statuses:
            age_days = max(age_days, self._status_age_limit_days(st, base_days, adaptive=adaptive))
        return age_days

    def compact_global_indexes(self, *, max_age_days: int = 180, adaptive: bool = True) -> Dict[str, int]:
        thread_idx = self._read_json(self._thread_index_path(), {"by_thread_id": {}, "recent_open_threads": []})
        tag_idx = self._read_json(self._tag_index_path(), {"by_tag": {}})
        status_idx = self._read_json(self._status_index_path(), {"by_status": {}})

        t_count = 0
        by_thread = dict(thread_idx.get("by_thread_id") or {})
        for tid, rows in list(by_thread.items()):
            age_days = self._age_days_with_status_mix(list(rows or []), max_age_days, adaptive=adaptive)
            compacted = self._compact_rows_by_age(list(rows or []), max_age_days=age_days, max_items=200)
            if compacted:
                by_thread[tid] = compacted
                t_count += len(compacted)
            else:
                by_thread.pop(tid, None)
        thread_idx["by_thread_id"] = by_thread
        thread_idx["recent_open_threads"] = self._compact_rows_by_age(
            list(thread_idx.get("recent_open_threads") or []),
            max_age_days=self._adaptive_age_days_for_rows(list(thread_idx.get("recent_open_threads") or []), max_age_days, adaptive=adaptive),
            max_items=300,
        )

        tag_count = 0
        by_tag = dict(tag_idx.get("by_tag") or {})
        for tag, rows in list(by_tag.items()):
            age_days = self._age_days_with_status_mix(list(rows or []), max_age_days, adaptive=adaptive)
            compacted = self._compact_rows_by_age(list(rows or []), max_age_days=age_days, max_items=200)
            if compacted:
                by_tag[tag] = compacted
                tag_count += len(compacted)
            else:
                by_tag.pop(tag, None)
        tag_idx["by_tag"] = by_tag

        status_count = 0
        by_status = dict(status_idx.get("by_status") or {})
        for st, rows in list(by_status.items()):
            age_days = self._status_age_limit_days(str(st), max_age_days, adaptive=adaptive)
            compacted = self._compact_rows_by_age(list(rows or []), max_age_days=age_days, max_items=300)
            if compacted:
                by_status[st] = compacted
                status_count += len(compacted)
            else:
                by_status.pop(st, None)
        status_idx["by_status"] = by_status

        self._write_json_atomic(self._thread_index_path(), thread_idx)
        self._write_json_atomic(self._tag_index_path(), tag_idx)
        self._write_json_atomic(self._status_index_path(), status_idx)
        return {"thread_rows": t_count, "tag_rows": tag_count, "status_rows": status_count}

    def get_index_snapshot(self) -> Dict[str, Any]:
        tpath = self._thread_index_path()
        g_missing = any(not os.path.exists(p) for p in [tpath, self._tag_index_path(), self._status_index_path()])
        if g_missing:
            self.rebuild_indexes()
        thread_doc = self._read_json(tpath, {"by_thread_id": {}, "recent_open_threads": []})
        if not isinstance(thread_doc, dict):
            self.rebuild_indexes()
            thread_doc = self._read_json(tpath, {"by_thread_id": {}, "recent_open_threads": []})
        return {
            "by_thread_id": thread_doc.get("by_thread_id", {}),
            "recent_open_threads": thread_doc.get("recent_open_threads", []),
            "by_tag": self._read_json(self._tag_index_path(), {"by_tag": {}}).get("by_tag", {}),
            "by_status": self._read_json(self._status_index_path(), {"by_status": {}}).get("by_status", {}),
        }

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

    def rebuild_indexes(self) -> None:
        for name in os.listdir(self.root_dir):
            if not name.endswith(".jsonl"):
                continue
            sid = name[:-6]
            self._rebuild_index(sid)
        self._write_json_atomic(self._thread_index_path(), {"by_thread_id": {}, "recent_open_threads": []})
        self._write_json_atomic(self._tag_index_path(), {"by_tag": {}})
        self._write_json_atomic(self._status_index_path(), {"by_status": {}})
        for name in os.listdir(self.root_dir):
            if not name.endswith(".jsonl"):
                continue
            sid = name[:-6]
            for item in self._iter_jsonl(sid):
                self._update_global_indexes(sid, item)
        self.compact_global_indexes(max_age_days=180, adaptive=True)

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
