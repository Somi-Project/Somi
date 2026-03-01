from __future__ import annotations

import re
from typing import Any, Iterable

from config.settings import STRATEGIC_EXECUTION_BYPASS_PHRASES

FORBIDDEN_KEYS = {"proposal_action", "tool_call", "capability_request"}
MAX_ALLOWED_ARTIFACT_IDS = 15
MAX_CONTEXT_ARTIFACT_IDS = 15


def deep_scan_forbidden_keys(data: Any, path: str = "$") -> list[str]:
    errs: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            k = str(key)
            p = f"{path}.{k}"
            if k in FORBIDDEN_KEYS:
                errs.append(f"forbidden_key:{p}")
            if k == "type" and str(value) == "proposal_action":
                errs.append(f"forbidden_type:{p}")
            errs.extend(deep_scan_forbidden_keys(value, p))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            errs.extend(deep_scan_forbidden_keys(item, f"{path}[{idx}]"))
    return errs


def is_execution_phrase(text: str, phrases: Iterable[str] | None = None) -> bool:
    lowered = str(text or "").lower()
    active = [str(x).strip().lower() for x in list(phrases or STRATEGIC_EXECUTION_BYPASS_PHRASES) if str(x).strip()]
    if not active:
        return False
    pattern = r"\b(" + "|".join(re.escape(x) for x in active) + r")\b"
    return bool(re.search(pattern, lowered))
