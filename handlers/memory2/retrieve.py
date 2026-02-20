from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(f: Dict) -> bool:
    ex = str(f.get("expires_at") or "").strip()
    if not ex:
        return False
    try:
        dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= _now()
    except Exception:
        return False


def active_facts(facts: List[Dict]) -> List[Dict]:
    out = []
    for f in facts:
        if str(f.get("status", "")) != "active":
            continue
        if _expired(f):
            continue
        out.append(f)
    return out


def get_profile_facts(facts: List[Dict]) -> List[Dict]:
    return [f for f in active_facts(facts) if f.get("kind") == "profile"]


def get_preference_facts(facts: List[Dict]) -> List[Dict]:
    return [f for f in active_facts(facts) if f.get("kind") == "preference"]


def get_constraint_facts(facts: List[Dict]) -> List[Dict]:
    return [f for f in active_facts(facts) if f.get("kind") == "constraint"]


def get_volatile_facts(facts: List[Dict]) -> List[Dict]:
    return [f for f in active_facts(facts) if f.get("kind") == "volatile"]


def get_relevant_facts(facts: List[Dict], query: str, limit: int = 8) -> List[Dict]:
    q = (query or "").lower()
    q_tokens = set(q.split())
    scored = []
    for f in active_facts(facts):
        key = str(f.get("key", "")).lower()
        val = str(f.get("value", "")).lower()
        score = 0
        if key and key in q:
            score += 2
        if any(tok in q_tokens for tok in key.replace("_", " ").split()):
            score += 2
        if any(tok in q_tokens for tok in val.split()):
            score += 2
        if any(tok in q for tok in ("preference", "prefer", "favorite")) and f.get("kind") == "preference":
            score += 1
        if score > 0:
            scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:limit]]


def get_relevant_skills(skills: List[Dict], query: str, limit: int = 3) -> List[Dict]:
    q = (query or "").lower()
    q_tokens = set(q.split())
    scored = []
    for s in skills:
        if not bool(s.get("success", True)):
            continue
        score = 0
        trigger = str(s.get("trigger", "")).lower()
        if trigger and any(t in trigger for t in q_tokens):
            score += 2
        for t in s.get("tags", []) or []:
            if str(t).lower() in q:
                score += 1
        for st in s.get("steps", []) or []:
            step = str(st).lower()
            if any(t in step for t in q_tokens):
                score += 1
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]]
