from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Journal:
    path: Path

    def append(self, kind: str, summary: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        evt = journal_event(kind, summary, data or {})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        return evt


def journal_event(kind: str, summary: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "summary": summary,
        "data": data or {},
    }
