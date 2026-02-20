from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from config.settings import MEMORY_CONF_MIN, MEMORY_EXTRACTION_ENABLED, MEMORY_MODEL


def to_snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:48] or "fact"


def heuristics(user_text: str, assistant_text: str = "") -> Dict[str, List[Dict[str, Any]]]:
    t = (user_text or "").strip()
    tl = t.lower()
    facts: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []

    if "don't output json" in tl or "dont output json" in tl or "no json" in tl:
        facts.append({"entity": "user", "key": "output_format", "value": "structured text", "kind": "preference", "confidence": 0.96})
    m = re.search(r"\bmy\s+favorite\s+color\s+is\s+([a-zA-Z ]{2,24})", tl)
    if m:
        facts.append({"entity": "user", "key": "favorite_color", "value": m.group(1).strip()[:24], "kind": "preference", "confidence": 0.93})
    m = re.search(r"\bmy\s+dog(?:'s)?\s+name\s+is\s+([a-zA-Z0-9 _'-]{1,32})", t, flags=re.IGNORECASE)
    if m:
        facts.append({"entity": "user", "key": "dog_name", "value": m.group(1).strip()[:32], "kind": "profile", "confidence": 0.9})
    m = re.search(r"\btimezone\s+is\s+([a-zA-Z0-9_\-/]+)", tl)
    if m:
        facts.append({"entity": "user", "key": "timezone", "value": m.group(1).strip()[:64], "kind": "profile", "confidence": 0.9})
    m = re.search(r"\bcall\s+me\s+([a-zA-Z0-9 _'-]{1,32})", t, flags=re.IGNORECASE)
    if m:
        kind = "volatile" if "for this session" in tl else "preference"
        facts.append({"entity": "user", "key": "preferred_name", "value": m.group(1).strip()[:32], "kind": kind, "confidence": 0.86})

    # skill heuristic: 3+ step-like lines in assistant output
    step_lines = [ln.strip("- ") for ln in (assistant_text or "").splitlines() if re.search(r"\b(run|edit|patch|set|create|use|check|test|open)\b", ln.lower())]
    if len(step_lines) >= 3:
        skills.append({"trigger": "procedural fix", "steps": step_lines[:8], "tags": ["auto", "replay"], "confidence": 0.7})

    return {"facts": facts[:3], "skills": skills[:1]}


def should_call_llm(user_text: str, assistant_text: str = "") -> bool:
    tl = (user_text or "").lower()
    triggers = ("my ", "i am", "i prefer", "call me", "timezone", "for this session", "from now on", "always", "don't")
    return any(t in tl for t in triggers) or ("worked" in tl or "fixed" in tl or "solved" in tl)


async def llm_extract(client, user_text: str, assistant_text: str = "", tool_summaries: List[str] | None = None) -> Dict[str, List[Dict[str, Any]]]:
    if not MEMORY_EXTRACTION_ENABLED or client is None:
        return {"facts": [], "skills": []}
    prompt = (
        "Return STRICT JSON only: {'facts':[...],'skills':[...]}. Be conservative. If uncertain return empty lists. "
        "facts fields: entity,key,value,kind(profile|preference|constraint|volatile),confidence. "
        "skills fields: trigger,steps,tags,confidence. max 3 facts, max 1 skill.\n"
        f"user={user_text}\nassistant={assistant_text}\ntools={tool_summaries or []}"
    )
    raw = "{}"
    try:
        resp = await client.chat(
            model=MEMORY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.0, "max_tokens": 260},
        )
        raw = resp.get("message", {}).get("content", "") or "{}"
        data = json.loads(raw)
    except Exception:
        # one repair retry
        try:
            fixed = raw.strip()
            fixed = fixed[fixed.find("{") : fixed.rfind("}") + 1] if "{" in fixed and "}" in fixed else "{}"
            data = json.loads(fixed)
        except Exception:
            return {"facts": [], "skills": []}

    facts = data.get("facts", []) if isinstance(data, dict) else []
    skills = data.get("skills", []) if isinstance(data, dict) else []
    if not isinstance(facts, list):
        facts = []
    if not isinstance(skills, list):
        skills = []
    return {"facts": facts[:3], "skills": skills[:1]}


def sanitize(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    out_facts, out_skills = [], []
    allow = {"timezone", "preferred_name", "output_format", "favorite_color", "dog_name", "default_location", "name"}
    for f in data.get("facts", []) or []:
        key = to_snake(str(f.get("key", "")))
        value = str(f.get("value", "")).strip()[:120]
        if not key or not value:
            continue
        conf = max(0.0, min(1.0, float(f.get("confidence", 0.6) or 0.6)))
        kind = str(f.get("kind", "preference")).strip().lower()
        if kind not in {"profile", "preference", "constraint", "volatile"}:
            kind = "preference"
        if conf < float(MEMORY_CONF_MIN) and key not in allow:
            continue
        if key not in allow and conf < 0.80:
            continue
        out_facts.append({"entity": "user", "key": key, "value": value, "kind": kind, "confidence": conf})

    for s in data.get("skills", []) or []:
        trig = str(s.get("trigger", "")).strip()[:120]
        if not trig:
            continue
        steps = [str(x).strip()[:90] for x in (s.get("steps", []) or []) if str(x).strip()][:8]
        tags = [to_snake(str(x))[:32] for x in (s.get("tags", []) or []) if str(x).strip()][:10]
        conf = max(0.0, min(1.0, float(s.get("confidence", 0.6) or 0.6)))
        if conf < float(MEMORY_CONF_MIN):
            continue
        out_skills.append({"trigger": trig, "steps": steps, "tags": tags, "confidence": conf})
    return {"facts": out_facts[:3], "skills": out_skills[:1]}
