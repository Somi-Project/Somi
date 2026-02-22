from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List

from handlers.prompting.blocks import PromptBlock
from handlers.prompting.budget import estimate_tokens


def write_prompt_snapshot(settings, flags: Dict[str, object], blocks: List[PromptBlock], trim_report: Dict[str, object], final_prompt: str) -> str:
    snapshot_dir = getattr(settings, "PROMPT_SNAPSHOT_DIR", os.path.join("sessions", "logs", "prompt_snapshots"))
    os.makedirs(snapshot_dir, exist_ok=True)

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    path = os.path.join(snapshot_dir, f"prompt_snapshot_{stamp}.json")

    payload = {
        "flags": flags,
        "block_token_counts": {b.key: estimate_tokens(b.content) for b in blocks},
        "trim_report": trim_report,
        "final_prompt": final_prompt,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
