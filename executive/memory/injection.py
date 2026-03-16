from __future__ import annotations

import json
from typing import Any, Dict, List

from config.memorysettings import MEMORY_MAX_TOTAL_CHARS
from executive.memory.curation import render_memory_block, sanitize_memory_lines, sanitize_payload_text


def _trim_lines(lines: List[str], limit: int) -> List[str]:
    out = []
    for ln in lines:
        ln2 = (ln or "").strip()
        if not ln2:
            continue
        out.append(ln2)
        if len(out) >= limit:
            break
    return out


def build_profile_block(rows: List[Dict]) -> str:
    lines = []
    for r in rows:
        k = str(r.get("mkey") or r.get("slot_key") or "fact").replace("_", " ").title()
        v = str(r.get("value") or r.get("text") or "").strip()
        if v:
            lines.append(f"- {k}: {v}")
    lines = _trim_lines(lines, 4)
    clean, _ = sanitize_memory_lines(lines, max_lines=4)
    return render_memory_block("Curated Profile", clean)


def build_preferences_block(rows: List[Dict]) -> str:
    lines = []
    for r in rows:
        k = str(r.get("mkey") or r.get("slot_key") or "pref").replace("_", " ").title()
        v = str(r.get("value") or r.get("text") or "").strip()
        if v:
            lines.append(f"- {k}: {v}")
    lines = _trim_lines(lines, 5)
    clean, _ = sanitize_memory_lines(lines, max_lines=5)
    return render_memory_block("Curated Preferences", clean)


def _entity_payload(row: Dict[str, Any]) -> dict[str, Any]:
    raw = row.get("entities_json")
    if isinstance(raw, dict):
        return dict(raw)
    try:
        return json.loads(str(raw or "{}"))
    except Exception:
        return {}


def build_typed_memory_block(title: str, rows: List[Dict]) -> str:
    lines = []
    for row in rows:
        payload = _entity_payload(row)
        name = str(payload.get("name") or row.get("mkey") or "item").replace("_", " ").title()
        value = str(row.get("text") or row.get("value") or "").strip()
        if value:
            lines.append(f"- {name}: {value[:180]}")
    clean, _ = sanitize_memory_lines(lines, max_lines=4)
    return render_memory_block(title, clean)


def build_session_summary_block(summary_text: str) -> str:
    t = (summary_text or "").strip()
    if not t:
        return render_memory_block("Working Session Summary", [])
    clean, _ = sanitize_memory_lines([f"- {t[:280]}"], max_lines=1, line_limit=280)
    return render_memory_block("Working Session Summary", clean)


def build_relevant_block(items: List[Dict]) -> str:
    lines = []
    for it in items:
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- {text[:180]}")
    lines = _trim_lines(lines, 8)
    clean, _ = sanitize_memory_lines(lines, max_lines=8)
    return render_memory_block("Relevant Recall", clean)


def build_vault_block(items: List[Dict]) -> str:
    lines = []
    for item in items:
        payload = _entity_payload(item)
        title = str(payload.get("title") or item.get("value") or "Vault").strip()
        location = str(payload.get("location") or "").strip()
        chunk = str(item.get("text") or "").strip()
        suffix = f" [{location}]" if location else ""
        if chunk:
            lines.append(f"- {title}{suffix}: {chunk[:150]}")
    clean, _ = sanitize_memory_lines(lines, max_lines=4, line_limit=220)
    return render_memory_block("Knowledge Vault", clean)


def build_operational_block(
    goal_rows: List[Dict] | None = None,
    reminder_rows: List[Dict] | None = None,
    operational_items: List[Dict] | None = None,
) -> str:
    lines = []
    for row in list(goal_rows or [])[:3]:
        title = str(row.get("title") or row.get("value") or "").strip()
        if title:
            lines.append(f"- Goal: {title[:150]}")
    for row in list(reminder_rows or [])[:3]:
        title = str(row.get("title") or "Reminder").strip()
        due_ts = str(row.get("due_ts") or "").strip()
        suffix = f" (due {due_ts[:16]})" if due_ts else ""
        lines.append(f"- Reminder: {title[:140]}{suffix}")
    for row in list(operational_items or [])[:4]:
        text = str(row.get("text") or row.get("snippet") or "").strip()
        if text:
            lines.append(f"- Recall: {text[:180]}")
    clean, _ = sanitize_memory_lines(lines, max_lines=8, line_limit=180)
    return render_memory_block("Operational Memory", clean)


def build_injection_payload(
    profile_rows: List[Dict],
    pref_rows: List[Dict],
    session_summary: str,
    relevant_items: List[Dict],
    *,
    goal_rows: List[Dict] | None = None,
    reminder_rows: List[Dict] | None = None,
    operational_items: List[Dict] | None = None,
    user_rows: List[Dict] | None = None,
    project_rows: List[Dict] | None = None,
    object_rows: List[Dict] | None = None,
    vault_rows: List[Dict] | None = None,
) -> str:
    chunks = [
        build_profile_block(profile_rows),
        build_preferences_block(pref_rows),
        build_typed_memory_block("User Memory", list(user_rows or [])),
        build_typed_memory_block("Project Memory", list(project_rows or [])),
        build_typed_memory_block("Object Memory", list(object_rows or [])),
        build_session_summary_block(session_summary),
        build_operational_block(goal_rows=goal_rows, reminder_rows=reminder_rows, operational_items=operational_items),
        build_vault_block(list(vault_rows or [])),
        build_relevant_block(relevant_items),
    ]
    out = "\n\n".join(chunks)
    cap = int(MEMORY_MAX_TOTAL_CHARS)
    return sanitize_payload_text(out, max_chars=cap)
