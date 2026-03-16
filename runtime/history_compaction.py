from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

COMPACTION_PREFIX = "[Compaction Summary]"


def _short(text: Any, limit: int = 180) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "..."


def _ledger_lines(state_ledger: dict[str, Any] | None, *, max_items: int = 3) -> list[str]:
    data = dict(state_ledger or {})
    lines: list[str] = []

    intent = _short(data.get("last_user_intent"), 180)
    if intent:
        lines.append(f"- Ledger intent: {intent}")

    for label, key in (
        ("Ledger goals", "goals"),
        ("Ledger decisions", "decisions"),
        ("Ledger open loops", "open_loops"),
        ("Ledger unresolved asks", "unresolved_asks"),
    ):
        rows = [str(x).strip() for x in list(data.get(key) or []) if str(x).strip()]
        if not rows:
            continue
        for row in rows[: max(1, int(max_items))]:
            lines.append(f"- {label}: {_short(row, 180)}")

    return lines


def build_compaction_summary(
    messages: list[dict[str, Any]],
    *,
    prior_summary: str = "",
    max_items: int = 8,
    max_chars: int = 1200,
    state_ledger: dict[str, Any] | None = None,
    operational_context: list[str] | None = None,
) -> str:
    """Create a deterministic, bounded summary from older transcript turns."""
    items: list[str] = []
    if prior_summary:
        prior = _short(prior_summary.replace(COMPACTION_PREFIX, "").strip(), 320)
        if prior:
            items.append(f"- Prior summary: {prior}")

    turn_pairs: list[tuple[str, str]] = []
    pending_user = ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        content = _short(msg.get("content"), 220)
        if not content:
            continue
        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user:
            turn_pairs.append((pending_user, content))
            pending_user = ""

    for user_text, assistant_text in turn_pairs[-max_items:]:
        items.append(f"- User asked: {user_text}")
        items.append(f"- Assistant answered: {assistant_text}")

    # Keep ledger state pinned in compacted context to improve follow-up continuity.
    items.extend(_ledger_lines(state_ledger, max_items=3))
    for row in list(operational_context or [])[:3]:
        text = _short(row, 180)
        if text:
            items.append(f"- Operational recall: {text}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = "\n".join(items).strip() or "- Earlier conversation was compacted due to length."
    result = f"{COMPACTION_PREFIX} refreshed {stamp}\n{summary}".strip()
    if max_chars > 0 and len(result) > max_chars:
        result = result[:max_chars].rstrip() + "..."
    return result
