from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from executive.life_modeling.schemas import inject_schema


class ArtifactStore:
    """Phase 7 artifact persistence with schema injection."""

    def __init__(self, root_dir: str = "sessions/artifacts/life_modeling"):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_type: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(artifact_type or "unknown"))
        return self.root / f"{safe}.jsonl"

    def write(self, artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = inject_schema(artifact_type, payload)
        with self._path(artifact_type).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def read_latest(self, artifact_type: str) -> dict[str, Any] | None:
        path = self._path(artifact_type)
        if not path.exists():
            return None
        last = None
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                txt = line.strip()
                if not txt:
                    continue
                try:
                    last = json.loads(txt)
                except Exception:
                    continue
        return inject_schema(artifact_type, last) if isinstance(last, dict) else None

    def iter_all(self, artifact_type: str) -> Iterable[dict[str, Any]]:
        path = self._path(artifact_type)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                txt = line.strip()
                if not txt:
                    continue
                try:
                    raw = json.loads(txt)
                except Exception:
                    continue
                if isinstance(raw, dict):
                    yield inject_schema(artifact_type, raw)
