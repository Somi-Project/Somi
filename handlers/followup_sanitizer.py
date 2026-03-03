from __future__ import annotations

import re

FOLLOWUP_INJECTION_MARKERS = (
    "previous query:",
    "previous top result:",
    "now answer this follow-up:",
    "decide whether to:",
    "build directly on the previous context",
    "you have the previous search results available",
)


def sanitize_user_visible_prompt(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("previous query:") or "now answer this follow-up:" in lower:
        m = re.search(r"now\s+answer\s+this\s+follow-up\s*:\s*(.+)", raw, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return (m.group(1) or "").strip().splitlines()[0].strip()
    return raw


def has_followup_injection_markers(text: str) -> bool:
    tl = str(text or "").lower()
    return any(marker in tl for marker in FOLLOWUP_INJECTION_MARKERS)
