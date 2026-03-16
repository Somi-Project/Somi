from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from config.memorysettings import MEMORY_CONF_MIN, MEMORY_EXTRACTION_ENABLED, MEMORY_MODEL


def to_snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:48] or "fact"


def _looks_like_food_preference(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # quick guardrails against obvious technical/professional phrases
    technical_markers = (
        "python", "javascript", "typescript", "rust", "golang", "java", "c++", "sql",
        "coding", "code", "repo", "framework", "api", "model", "research", "paper",
    )
    if any(m in t for m in technical_markers):
        return False

    # explicit food/drink context words
    food_context = (
        "food", "foods", "snack", "snacks", "drink", "drinks", "tea", "coffee", "fruit",
        "meal", "dessert", "breakfast", "lunch", "dinner", "juice",
    )
    if any(m in t for m in food_context):
        return True

    # single-item preference strings (e.g., "blueberries") are treated as likely food preferences
    return len(t.split()) <= 3


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

    m = re.search(r"\bmy\s+name\s+is\s+([a-zA-Z0-9 _'-]{1,40})", t, flags=re.IGNORECASE)
    if m:
        facts.append({"entity": "user", "key": "name", "value": m.group(1).strip()[:40], "kind": "profile", "confidence": 0.96})

    m = re.search(r"\bmy\s+favorite\s+drink\s+is\s+([a-zA-Z0-9 _'-]{1,48})", t, flags=re.IGNORECASE)
    if m:
        facts.append({"entity": "user", "key": "favorite_drink", "value": m.group(1).strip()[:48], "kind": "preference", "confidence": 0.95})

    m = re.search(r"\bupdate\s*:\s*my\s+favorite\s+drink\s+is\s+now\s+([a-zA-Z0-9 _'-]{1,48})", t, flags=re.IGNORECASE)
    if m:
        facts.append({"entity": "user", "key": "favorite_drink", "value": m.group(1).strip()[:48], "kind": "preference", "confidence": 0.97})

    m = re.search(r"\bi\s+(?:love|like|prefer|am\s+into)\s+([a-zA-Z0-9 _'-]{2,48})", t, flags=re.IGNORECASE)
    if m:
        pref_text = m.group(1).strip()[:48]
        pref_key = "favorite_food" if _looks_like_food_preference(pref_text) else "user_preference"
        facts.append({"entity": "user", "key": pref_key, "value": pref_text, "kind": "preference", "confidence": 0.84})

    if re.search(r"\bwhen\s+i\s+ask\s+for\s+code", tl) and "python" in tl:
        facts.append({"entity": "user", "key": "coding_style", "value": "Python 3.11+ and type hints", "kind": "preference", "confidence": 0.9})

    if "run memory test" in tl and "tools/memory_e2e_test.py" in tl:
        facts.append({"entity": "user", "key": "run_memory_test_command", "value": "tools/memory_e2e_test.py", "kind": "preference", "confidence": 0.88})

    # skill heuristic: 3+ step-like lines in assistant output
    step_lines = [ln.strip("- ") for ln in (assistant_text or "").splitlines() if re.search(r"\b(run|edit|patch|set|create|use|check|test|open)\b", ln.lower())]
    if len(step_lines) >= 3:
        skills.append({"trigger": "procedural fix", "steps": step_lines[:8], "tags": ["auto", "replay"], "confidence": 0.7})

    return {"facts": facts[:8], "skills": skills[:1]}


def should_call_llm(user_text: str, assistant_text: str = "") -> bool:
    tl = (user_text or "").lower()
    triggers = (
        "my ", "i am", "i prefer", "i like", "i love", "i hate", "i'm into", "im into",
        "call me", "timezone", "for this session", "from now on", "always", "don't", "dont",
        "as a ", "i work as", "i teach", "i research", "i code in", "please remember",
    )
    return any(t in tl for t in triggers) or ("worked" in tl or "fixed" in tl or "solved" in tl)


def _coerce_llm_payload(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize alternate JSON shapes into canonical {'facts': [...], 'skills': [...]} payload."""
    if not isinstance(data, dict):
        return {"facts": [], "skills": []}

    facts = data.get("facts", [])
    skills = data.get("skills", [])

    if not isinstance(facts, list):
        facts = []
    if not isinstance(skills, list):
        skills = []

    # Support generic single-object memory outputs, e.g.
    # {"memory_text":"I love blueberries","category":"food","emotion":"positive"}
    if not facts:
        memory_text = str(data.get("memory_text", "")).strip()
        category = to_snake(str(data.get("category", "")).strip())
        if memory_text and category:
            mapped_key = "favorite_food" if category in {"food", "drink", "snack"} else "user_preference"
            facts.append(
                {
                    "entity": "user",
                    "key": mapped_key,
                    "value": memory_text[:120],
                    "kind": "preference",
                    "confidence": 0.82,
                }
            )

    return {"facts": facts[:8], "skills": skills[:1]}


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

    return _coerce_llm_payload(data)


def _normalize_key_value(key: str, value: str) -> tuple[str, str]:
    k = to_snake(key)
    v = (value or "").strip()[:120]

    if k in {"fav_color", "colour", "favorite_colour"}:
        k = "favorite_color"
    elif k in {"fav_drink", "favorite_beverage"}:
        k = "favorite_drink"
    elif k in {"fav_food", "favorite_snack", "liked_food", "food_preference"}:
        k = "favorite_food"
    elif k in {"job", "occupation", "profession"}:
        k = "work_role"
    elif k in {"risk", "risk_tolerance", "risk_appetite"}:
        k = "risk_profile"
    elif k in {"style", "communication_preference"}:
        k = "communication_style"

    return k, v


def sanitize(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    out_facts, out_skills = [], []
    allow = {
        "timezone", "preferred_name", "output_format", "favorite_color", "favorite_drink", "favorite_food",
        "dog_name", "default_location", "name", "coding_style", "run_memory_test_command",
        "work_role", "communication_style", "risk_profile", "primary_goal", "user_preference",
    }
    for f in data.get("facts", []) or []:
        key, value = _normalize_key_value(str(f.get("key", "")), str(f.get("value", "")))
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
    return {"facts": out_facts[:8], "skills": out_skills[:1]}
