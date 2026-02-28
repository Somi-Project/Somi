from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import LLMEnvelope


def _extract_action_lines(text: str) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[str] = []
    in_section = False
    for ln in lines:
        low = ln.lower()
        if any(h in low for h in ["action items:", "todo:", "next steps:", "tareas:", "próximos pasos:", "proximos pasos:"]):
            in_section = True
            continue
        if in_section and re.match(r"^[A-Za-z][A-Za-z ]{1,20}:$", ln):
            in_section = False
        if in_section or re.match(r"^\s*(?:[-*]|\d+[.)])\s+", ln):
            out.append(ln)
    return out[:25]


def build_action_items(*, query: str, route: str, envelope: LLMEnvelope, trigger_reason: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = "\n".join([query or "", envelope.answer_text or ""]).strip()
    rows = []
    for ln in _extract_action_lines(text):
        clean = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", ln).strip()
        owner = "Unassigned"
        task = clean
        due = None
        m = re.match(r"^([A-Za-z][A-Za-z .'-]{1,30})\s*[-:]\s*(.+)$", clean)
        if m:
            owner = m.group(1).strip()
            task = m.group(2).strip()
        d = re.search(r"\b(?:due|by)\s+([^,;]+)$", task, flags=re.IGNORECASE)
        if d:
            due = d.group(1).strip()
            task = re.sub(r"\b(?:due|by)\s+([^,;]+)$", "", task, flags=re.IGNORECASE).strip(" ,.-")
        if task:
            rows.append({"owner": owner, "task": task[:240], "due": due, "priority": None})
    warnings = []
    if not rows:
        warnings.append("No actionable tasks were confidently detected")
    return build_base(
        artifact_type="action_items",
        inputs={"user_query": query, "route": route},
        content={"title": "Action Items", "items": rows[:25], "extra_sections": []},
        citations=[],
        confidence=0.76,
        metadata={"derived_from": "notes_parser"},
        trigger_reason=trigger_reason,
    )


def build_status_update(*, query: str, route: str, envelope: LLMEnvelope, trigger_reason: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = "\n".join([query or "", envelope.answer_text or ""]).strip()
    buckets = {"done": [], "doing": [], "blocked": [], "next": [], "asks": [], "risks": []}
    current = None
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        low = ln.lower()
        mapped = None
        aliases = {"done": ["done:" , "hecho:"], "doing": ["doing:", "haciendo:"], "blocked": ["blocked:", "bloqueado:"], "next": ["next:"], "asks": ["asks:"], "risks": ["risks:"]}
        for k, prefixes in aliases.items():
            if any(low.startswith(pref) for pref in prefixes):
                mapped = k
                break
        if mapped:
            current = mapped
            rest = ln.split(":", 1)[1].strip()
            if rest:
                buckets[current].append(rest)
            continue
        if current and re.match(r"^\s*(?:[-*]|\d+[.)])\s+", ln):
            buckets[current].append(re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", ln))
    for k, mx in [("done", 12), ("doing", 12), ("blocked", 12), ("next", 12), ("asks", 8), ("risks", 8)]:
        buckets[k] = [x.strip()[:240] for x in buckets[k] if x.strip()][:mx]
    return build_base(
        artifact_type="status_update",
        inputs={"user_query": query, "route": route},
        content={"period": None, **buckets, "extra_sections": []},
        citations=[],
        confidence=0.74,
        metadata={"derived_from": "status_parser"},
        trigger_reason=trigger_reason,
    )
