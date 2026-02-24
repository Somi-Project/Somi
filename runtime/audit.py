from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def audit_path(job_id: str) -> Path:
    return Path("sessions/jobs") / job_id / "audit.jsonl"


def append_event(
    job_id: str, event: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "data": data or {},
    }
    path = audit_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
