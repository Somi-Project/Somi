from __future__ import annotations

import re
from typing import Any

_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_text(text: Any, *, max_chars: int = 4000) -> str:
    """Normalize text for in-memory transcript safety and token stability."""
    if text is None:
        return ""
    value = str(text)
    # Keep tabs/newlines, drop other control chars that often poison transcript shape.
    value = _CONTROL_RE.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.strip()
    if max_chars > 0 and len(value) > max_chars:
        keep = max(0, max_chars - len("\n...[truncated]"))
        value = (value[:keep].rstrip() + "\n...[truncated]").strip()
    return value


def sanitize_history_messages(
    history: list[dict[str, Any]] | None,
    *,
    max_messages: int = 120,
    max_message_chars: int = 4000,
) -> list[dict[str, str]]:
    """Return a cleaned role/content transcript list suitable for prompt assembly."""
    if not history:
        return []

    out: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role_raw = str(item.get("role") or "").strip().lower()
        role = role_raw if role_raw in {"user", "assistant", "system"} else "user"
        content = sanitize_text(item.get("content"), max_chars=max_message_chars)
        if not content:
            continue
        out.append({"role": role, "content": content})

    if max_messages > 0 and len(out) > max_messages:
        out = out[-max_messages:]
    return out
