from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from ollama import AsyncClient
except Exception:  # pragma: no cover
    AsyncClient = None  # type: ignore

from config.settings import MEMORY_MODEL, MEMORY2_EXTRACTION_ENABLED, MEMORY2_VOLATILE_TTL_HOURS
from .types import FactCandidate, SkillCandidate


TRIGGERS = (
    "my ", "i am", "i'm", "i prefer", "call me", "timezone", "located", "from now on", "don't", "dont", "always", "for this session"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:48] or "fact"


def _cap(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n]


def heuristic_extract(user_text: str) -> List[FactCandidate]:
    t = (user_text or "").strip()
    tl = t.lower()
    out: List[FactCandidate] = []


    if "dont output json" in tl or "don't output json" in tl:
        out.append(FactCandidate(entity="user", key="output_format", value="no_json", kind="preference", confidence=0.95))

    m = re.search(r"\bmy\s+favorite\s+color\s+is\s+([a-zA-Z ]{2,24})", tl)
    if m:
        out.append(FactCandidate(entity="user", key="favorite_color", value=_cap(m.group(1), 24), kind="preference", confidence=0.92))

    m = re.search(r"\bmy\s+dog(?:'s)?\s+name\s+is\s+([a-zA-Z0-9 _'-]{1,32})", t, flags=re.IGNORECASE)
    if m:
        out.append(FactCandidate(entity="user", key="dog_name", value=_cap(m.group(1), 40), kind="profile", confidence=0.9))
    m = re.search(r"\b(?:my\s+timezone\s+is|timezone\s+is)\s+([a-zA-Z0-9_\-/]+)", tl)
    if m:
        out.append(FactCandidate(entity="user", key="timezone", value=_cap(m.group(1), 64), kind="profile", confidence=0.92))

    m = re.search(r"\bcall\s+me\s+([a-zA-Z0-9 _'-]{1,32})", t, flags=re.IGNORECASE)
    if m:
        kind = "volatile" if "for this session" in tl else "preference"
        expires_at = None
        if kind == "volatile":
            expires_at = (_utcnow() + timedelta(hours=int(MEMORY2_VOLATILE_TTL_HOURS))).isoformat()
        out.append(FactCandidate(entity="user", key="preferred_name", value=_cap(m.group(1), 40), kind=kind, confidence=0.88, expires_at=expires_at))

    m = re.search(r"\bi\s+(?:really\s+)?(?:like|love|prefer)\s+([a-zA-Z0-9 ':-]{1,48})", tl)
    if m:
        out.append(FactCandidate(entity="user", key="likes", value=_cap(m.group(1), 60), kind="preference", confidence=0.8))

    m = re.search(r"\b(?:don't|dont|do not)\s+([a-zA-Z0-9 ':-]{1,48})", tl)
    if m:
        out.append(FactCandidate(entity="user", key="constraint", value=_cap(m.group(1), 60), kind="constraint", confidence=0.85))

    return out


def should_attempt_llm(user_text: str, assistant_text: Optional[str] = None) -> bool:
    tl = (user_text or "").lower()
    if any(k in tl for k in TRIGGERS):
        return True
    if assistant_text and "success" in assistant_text.lower():
        return True
    return False


async def llm_extract(
    client,
    user_text: str,
    assistant_text: Optional[str] = None,
    tool_summaries: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    if (not MEMORY2_EXTRACTION_ENABLED) or client is None:
        return {"facts": [], "skills": []}

    prompt = (
        "Extract conservative memory candidates. Return STRICT JSON only with keys facts and skills. "
        "If uncertain return empty arrays. facts entries: entity,key,value,kind(profile|preference|constraint|volatile),confidence. "
        "skills entries: trigger,steps,tools,tags,confidence. Keep short.\n"
        f"User: {user_text}\nAssistant: {assistant_text or ''}\nTools: {(tool_summaries or [])}"
    )
    try:
        resp = await client.chat(
            model=MEMORY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.0, "max_tokens": 260},
        )
        raw = resp.get("message", {}).get("content", "") or "{}"
        data = json.loads(raw)
        facts = data.get("facts", []) if isinstance(data, dict) else []
        skills = data.get("skills", []) if isinstance(data, dict) else []
        if not isinstance(facts, list):
            facts = []
        if not isinstance(skills, list):
            skills = []
        return {"facts": facts, "skills": skills}
    except Exception:
        return {"facts": [], "skills": []}


def normalize_fact_candidate(d: Dict[str, Any]) -> Optional[FactCandidate]:
    try:
        key = _snake(str(d.get("key", "")))
        value = _cap(str(d.get("value", "")), 120)
        if not key or not value:
            return None
        kind = str(d.get("kind", "preference")).strip().lower()
        if kind not in {"profile", "preference", "constraint", "volatile"}:
            kind = "preference"
        conf = float(d.get("confidence", 0.6) or 0.6)
        conf = max(0.0, min(1.0, conf))
        expires_at = None
        if kind == "volatile":
            expires_at = (_utcnow() + timedelta(hours=int(MEMORY2_VOLATILE_TTL_HOURS))).isoformat()
        return FactCandidate(entity=_snake(str(d.get("entity", "user"))) or "user", key=key, value=value, kind=kind, confidence=conf, expires_at=expires_at)
    except Exception:
        return None


def normalize_skill_candidate(d: Dict[str, Any]) -> Optional[SkillCandidate]:
    try:
        trigger = _cap(str(d.get("trigger", "")), 120)
        if not trigger:
            return None
        steps = [_cap(str(x), 120) for x in (d.get("steps", []) or []) if str(x).strip()][:8]
        tools = [_snake(str(x))[:32] for x in (d.get("tools", []) or []) if str(x).strip()][:8]
        tags = [_snake(str(x))[:32] for x in (d.get("tags", []) or []) if str(x).strip()][:10]
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.6) or 0.6)))
        return SkillCandidate(trigger=trigger, steps=steps, tools=tools, tags=tags, confidence=conf, success=True)
    except Exception:
        return None
