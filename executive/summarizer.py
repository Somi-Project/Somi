from __future__ import annotations

import json
from pathlib import Path


def write_executive_summary(intent_id: str, data: dict) -> str:
    out = Path("executive/summaries") / f"{intent_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(out)
