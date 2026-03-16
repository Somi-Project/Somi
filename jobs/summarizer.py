from __future__ import annotations

import json
from pathlib import Path


def write_job_summary(job_id: str, payload: dict, out_dir: str = "jobs/history") -> str:
    path = Path(out_dir) / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)
