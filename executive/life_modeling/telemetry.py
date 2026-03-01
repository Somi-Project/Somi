from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Phase7Telemetry:
    def __init__(self, path: str = "executive/index/phase7_telemetry.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"updated_at": None, "queue": {}, "shards": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("queue", {})
                data.setdefault("shards", {})
                return data
        except Exception:
            pass
        return {"updated_at": None, "queue": {}, "shards": {}}

    def _write(self, payload: dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def record_queue_depth(self, depth: int) -> None:
        doc = self._read()
        q = doc.setdefault("queue", {})
        q["current_depth"] = int(max(0, depth))
        q["max_depth_seen"] = max(int(q.get("max_depth_seen") or 0), int(max(0, depth)))
        q["depth_samples"] = int(q.get("depth_samples") or 0) + 1
        self._write(doc)

    def record_queue_resolution(self, *, approved: bool, latency_seconds: float | None) -> None:
        doc = self._read()
        q = doc.setdefault("queue", {})
        k = "approved_count" if approved else "rejected_count"
        q[k] = int(q.get(k) or 0) + 1
        if approved and latency_seconds is not None and latency_seconds >= 0:
            total = float(q.get("approval_latency_total_s") or 0.0) + float(latency_seconds)
            count = int(q.get("approval_latency_samples") or 0) + 1
            q["approval_latency_total_s"] = total
            q["approval_latency_samples"] = count
            q["approval_latency_avg_s"] = total / float(max(1, count))
        self._write(doc)

    def record_shard_files(self, file_count: int) -> None:
        doc = self._read()
        s = doc.setdefault("shards", {})
        s["current_files"] = int(max(0, file_count))
        s["max_files_seen"] = max(int(s.get("max_files_seen") or 0), int(max(0, file_count)))
        s["samples"] = int(s.get("samples") or 0) + 1
        self._write(doc)
