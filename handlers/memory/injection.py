from __future__ import annotations

from typing import Dict, List

from config.settings import MEMORY_MAX_TOTAL_CHARS


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
    return "[Profile]\n" + ("\n".join(lines) if lines else "- (none)")


def build_preferences_block(rows: List[Dict]) -> str:
    lines = []
    for r in rows:
        k = str(r.get("mkey") or r.get("slot_key") or "pref").replace("_", " ").title()
        v = str(r.get("value") or r.get("text") or "").strip()
        if v:
            lines.append(f"- {k}: {v}")
    lines = _trim_lines(lines, 5)
    return "[Preferences]\n" + ("\n".join(lines) if lines else "- (none)")


def build_session_summary_block(summary_text: str) -> str:
    t = (summary_text or "").strip()
    if not t:
        return "[Session Summary]\n- (none)"
    return "[Session Summary]\n- " + t[:280]


def build_relevant_block(items: List[Dict]) -> str:
    lines = []
    for it in items:
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- {text[:180]}")
    lines = _trim_lines(lines, 8)
    return "[Relevant]\n" + ("\n".join(lines) if lines else "- (none)")


def build_injection_payload(profile_rows: List[Dict], pref_rows: List[Dict], session_summary: str, relevant_items: List[Dict]) -> str:
    chunks = [
        build_profile_block(profile_rows),
        build_preferences_block(pref_rows),
        build_session_summary_block(session_summary),
        build_relevant_block(relevant_items),
    ]
    out = "\n\n".join(chunks)
    cap = int(MEMORY_MAX_TOTAL_CHARS)
    return out if len(out) <= cap else out[:cap]
