from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


class Indexer:
    def __init__(self, artifacts_dir: str = "sessions/artifacts", index_dir: str = "executive/index"):
        self.artifacts_dir = Path(artifacts_dir)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.index_dir / "artifact_index.json"
        self.state_path = self.index_dir / "index_state.json"

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"items": []}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"items": []}

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"files": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"files": {}}

    def _write_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        txt = line.strip()
        if not txt:
            return None
        try:
            row = json.loads(txt)
        except Exception:
            return None
        return row if isinstance(row, dict) else None

    def _scan_incremental(self, path: Path, prev: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        prev_size = int(prev.get("size") or 0)
        prev_count = int(prev.get("count") or 0)
        prev_last = dict(prev.get("last_row") or {})

        size = path.stat().st_size
        if size < prev_size:
            prev_size = 0
            prev_count = 0
            prev_last = {}

        count = prev_count
        last = prev_last
        with path.open("rb") as f:
            f.seek(prev_size)
            while True:
                bline = f.readline()
                if not bline:
                    break
                row = self._parse_line(bline.decode("utf-8", errors="ignore"))
                if row is None:
                    continue
                count += 1
                last = row

        meta = {
            "path": str(path),
            "artifact_type": str(last.get("artifact_type") or last.get("contract_name") or ""),
            "thread_id": last.get("thread_id"),
            "tags": list(last.get("tags") or [])[:20],
            "updated_at": last.get("updated_at") or last.get("timestamp"),
            "count": count,
        }
        state = {
            "size": size,
            "count": count,
            "last_row": last,
            "last_line_hash": hashlib.sha1(json.dumps(last, sort_keys=True).encode("utf-8")).hexdigest() if last else "",
        }
        return meta, state

    def build_or_update_index(self) -> dict[str, Any]:
        idx = self.load_index()
        state = self._load_state()
        by_file = {str(x.get("path")): x for x in list(idx.get("items") or []) if isinstance(x, dict)}
        file_state = dict(state.get("files") or {})

        for file in sorted(self.artifacts_dir.glob("*.jsonl")):
            key = str(file)
            prev = dict(file_state.get(key) or {})
            try:
                stat = file.stat()
            except Exception:
                continue
            if int(prev.get("size") or -1) == int(stat.st_size):
                continue
            try:
                meta, st = self._scan_incremental(file, prev)
            except Exception:
                continue
            by_file[key] = meta
            file_state[key] = st

        existing = {str(p) for p in self.artifacts_dir.glob("*.jsonl")}
        by_file = {k: v for k, v in by_file.items() if k in existing}
        file_state = {k: v for k, v in file_state.items() if k in existing}

        out = {"items": list(by_file.values())}
        self._write_atomic(self.index_path, out)
        self._write_atomic(self.state_path, {"files": file_state})
        return out

    def iter_recent_artifacts(self, days: int, types: list[str] | None = None) -> Iterable[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        allow = {str(t) for t in list(types or [])}
        for meta in list(self.load_index().get("items") or []):
            if not isinstance(meta, dict):
                continue
            if allow and str(meta.get("artifact_type") or "") not in allow:
                continue
            ts = str(meta.get("updated_at") or "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt >= cutoff:
                yield {
                    "path": str(meta.get("path") or ""),
                    "artifact_type": str(meta.get("artifact_type") or ""),
                    "thread_id": meta.get("thread_id"),
                    "tags": list(meta.get("tags") or []),
                    "updated_at": ts,
                    "count": int(meta.get("count") or 0),
                }


_default = Indexer()


def load_index() -> dict[str, Any]:
    return _default.load_index()


def build_or_update_index() -> dict[str, Any]:
    return _default.build_or_update_index()


def iter_recent_artifacts(days: int, types: list[str] | None = None) -> Iterable[dict[str, Any]]:
    return _default.iter_recent_artifacts(days, types)
