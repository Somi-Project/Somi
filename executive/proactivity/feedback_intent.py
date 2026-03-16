from __future__ import annotations

import re

TOPIC_ALIASES = {
    "weather": "weather",
    "news": "news",
    "market": "markets",
    "markets": "markets",
    "task": "tasks",
    "tasks": "tasks",
    "alert": "alerts",
    "alerts": "alerts",
    "brief": "strategic_signals",
}


def _topic(text: str) -> str:
    low = text.lower()
    if "morning brief" in low:
        return "morning_brief"
    if "evening brief" in low:
        return "evening_brief"
    for k, v in TOPIC_ALIASES.items():
        if re.search(rf"\b{k}\b", low):
            return v
    return "strategic_signals"


def _parse_time(low: str) -> str | None:
    m = re.search(r"(?:to|at)\s*([0-9]{1,2})(?::([0-9]{2}))?\s*(am|pm)?", low)
    if not m:
        return None
    hh, mm, ap = m.groups()
    h = int(hh)
    mi = int(mm or 0)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not 0 <= h <= 23 or not 0 <= mi <= 59:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_feedback_intent(text: str) -> dict:
    low = (text or "").strip().lower()
    topic = _topic(low)
    out = {
        "type": "preference_update_v1",
        "topic": topic,
        "scope": "global",
        "mode": "disable",
        "time": None,
        "duration": "forever",
        "ttl_days": 0,
        "source_text": text,
        "no_autonomy": True,
    }

    if re.search(r"\b(start|enable|again|resume)\b", low):
        out["mode"] = "enable"
    if re.search(r"\bonly\s+alerts|alerts\s+only\b", low):
        out["mode"] = "alerts_only"
    if "more of this" in low:
        out["mode"] = "notify"
    if "less of this" in low:
        out["mode"] = "brief_only"

    if "today" in low:
        out["duration"] = "today"
    if re.search(r"\bsnooze\b", low):
        out["mode"] = "snooze"
        out["duration"] = "days"
        qty = re.search(r"(\d+)\s*(day|days|week|weeks)", low)
        if qty:
            n = int(qty.group(1))
            if "week" in qty.group(2):
                n *= 7
            out["ttl_days"] = n
        else:
            out["ttl_days"] = 7
    if re.search(r"\b(no|stop|don't remind me|dont remind me|forget)\b", low):
        out["mode"] = "disable"

    brief_time = re.search(r"(?:set|move)\s+(morning|evening)\s+brief", low)
    if brief_time:
        out["topic"] = f"{brief_time.group(1)}_brief"
        out["mode"] = "update_time"
        out["time"] = _parse_time(low)
        if out["time"] is None:
            out["clarification_needed"] = True
            out["clarification_question"] = "What time should I set it to?"

    if re.search(r"disable\s+(morning|evening)\s+brief", low):
        p = re.search(r"(morning|evening)", low).group(1)
        out["topic"] = f"{p}_brief"
        out["mode"] = "disable"
        out["time"] = None

    if low.strip() in {"forget that", "nope", "that"}:
        out["clarification_needed"] = True
        out["clarification_question"] = "Do you want me to pause alerts, briefs, or both?"
    return out
