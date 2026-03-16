from __future__ import annotations

import json
import os
from typing import Any, Dict, List


_PERSONA_FIELDS = ("role", "description", "behaviors", "inhibitions", "hobbies", "experience", "physicality")


def _resolve_persona_file(settings) -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    configured = getattr(settings, "PERSONALITY_CONFIG_PATH", "config/personalC.json")
    if os.path.isabs(configured):
        return configured
    return os.path.join(base_dir, configured)


def _pick_agent_key(payload: Dict[str, Any], settings) -> str:
    preferred = getattr(settings, "PROMPT_PERSONA_NAME", "Name: Somi")
    if preferred in payload:
        return preferred
    for key in payload.keys():
        if str(key).startswith("Name: "):
            return str(key)
    return next(iter(payload.keys()), "")


def _normalize_list(values: Any, limit: int = 6) -> List[str]:
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        s = str(item).strip()
        if s:
            out.append(s)
    return out[:limit]


def load_persona_text(settings) -> str:
    path = _resolve_persona_file(settings)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    key = _pick_agent_key(payload, settings)
    persona = payload.get(key, {}) if isinstance(payload, dict) else {}

    role = str(persona.get("role", "assistant")).strip()
    description = str(persona.get("description", "")).strip()
    behaviors = _normalize_list(persona.get("behaviors"), limit=8)
    inhibitions = _normalize_list(persona.get("inhibitions"), limit=4)
    hobbies = _normalize_list(persona.get("hobbies"), limit=4)
    experience = _normalize_list(persona.get("experience"), limit=3)

    lines = [
        f"Identity: {key.replace('Name: ', '').strip() or 'Somi'}",
        f"Role style: {role}",
    ]
    if description:
        lines.append(f"Voice/tone preference: {description}")
    if behaviors:
        lines.append("Conversational habits: " + "; ".join(behaviors))
    if hobbies:
        lines.append("User experience goals: " + "; ".join(hobbies))
    if experience:
        lines.append("Contextual strengths: " + "; ".join(experience))
    if inhibitions:
        lines.append("Style do/don't rules: " + "; ".join(inhibitions))

    return "\n".join(lines).strip()
