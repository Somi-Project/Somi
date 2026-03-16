from __future__ import annotations

import re
from typing import Any, Callable


FactGenerator = Callable[[str, dict[str, Any]], str]


def _allowed_tokens(facts: dict[str, Any]) -> set[str]:
    toks: set[str] = set()
    for key in ["impacts", "patterns", "calendar_conflicts", "evidence_artifact_ids"]:
        for row in list(facts.get(key) or []):
            if isinstance(row, dict):
                for v in row.values():
                    if isinstance(v, (str, int, float)):
                        toks.add(str(v).lower())
                    if isinstance(v, list):
                        for x in v:
                            toks.add(str(x).lower())
            else:
                toks.add(str(row).lower())
    return {t for t in toks if t}


def _validate_fact_locked(summary: str, facts: dict[str, Any]) -> bool:
    text = str(summary or "").lower()
    if not text:
        return False
    allowed = _allowed_tokens(facts)
    ids = set(re.findall(r"\b(?:proj|goal|pattern|cand|glp)_[a-z0-9]{6,}\b", text))
    if any(i not in allowed for i in ids):
        return False
    nums = [int(x) for x in re.findall(r"\b\d+\b", text)]
    max_safe = (
        len(list(facts.get("impacts") or []))
        + len(list(facts.get("patterns") or []))
        + len(list(facts.get("calendar_conflicts") or []))
        + 50
    )
    if any(n > max_safe for n in nums):
        return False
    return True


def enrich_summary(summary: str, facts: dict[str, Any], mode: str = "lite", generator: FactGenerator | None = None) -> tuple[str, bool]:
    mode = str(mode or "lite")
    if mode == "off":
        return summary, True
    try:
        impacts = len(list(facts.get("impacts") or []))
        patterns = len(list(facts.get("patterns") or []))
        conflicts = len(list(facts.get("calendar_conflicts") or []))
        base = f"Heartbeat v2: {impacts} impact chain(s), {patterns} notable pattern(s), {conflicts} calendar conflict(s). {summary}"
        if mode == "lite" or generator is None:
            return base, True
        candidate = str(generator(base, facts) or "").strip()
        if _validate_fact_locked(candidate, facts):
            return candidate, True
        return base, False
    except Exception:
        return summary, False
