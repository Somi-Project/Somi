from __future__ import annotations

import re
from typing import Iterable


SUSPICIOUS_PATTERNS = [
    re.compile(r"\bignore\s+(?:all|any|previous|above)\s+instructions\b", flags=re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", flags=re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", flags=re.IGNORECASE),
    re.compile(r"\btool\s*call\b", flags=re.IGNORECASE),
    re.compile(r"^\s*(?:role\s*:|assistant\s*:|system\s*:|developer\s*:)", flags=re.IGNORECASE),
    re.compile(r"`{3,}"),
    re.compile(r"<\s*/?\s*(?:system|assistant|developer|tool)\b", flags=re.IGNORECASE),
]


def _clip(text: str, *, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def sanitize_memory_lines(
    lines: Iterable[str],
    *,
    max_lines: int,
    line_limit: int = 180,
) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    issues: list[str] = []
    for raw in lines:
        line = _clip(str(raw or "").strip(), limit=line_limit)
        if not line:
            continue
        suspicious = False
        for pattern in SUSPICIOUS_PATTERNS:
            if pattern.search(line):
                suspicious = True
                issues.append(f"dropped:{line[:80]}")
                break
        if suspicious:
            continue
        kept.append(line)
        if len(kept) >= max(1, int(max_lines)):
            break
    return kept, issues


def render_memory_block(title: str, lines: Iterable[str]) -> str:
    rows = [str(line or "").strip() for line in lines if str(line or "").strip()]
    body = "\n".join(rows) if rows else "- (none)"
    return f"[{title}]\n{body}"


def sanitize_payload_text(text: str, *, max_chars: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= max(1, int(max_chars)):
        return clean
    limit = max(0, int(max_chars) - 3)
    return clean[:limit].rstrip() + "..."
