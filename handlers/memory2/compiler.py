from __future__ import annotations

from typing import Dict, List

from config.settings import MEMORY2_MAX_FACT_LINES, MEMORY2_MAX_SKILL_LINES, MEMORY2_MAX_TOTAL_CHARS


def _line(s: str, max_len: int = 160) -> str:
    s = (s or "").strip()
    return s if len(s) <= max_len else s[: max_len - 3].rstrip() + "..."


def compile_memory_block(
    profile: List[Dict],
    preferences: List[Dict],
    constraints: List[Dict],
    volatile: List[Dict],
    relevant_skills: List[Dict],
    relevant_facts: List[Dict],
) -> str:
    max_fact_lines = max(1, int(MEMORY2_MAX_FACT_LINES))
    max_skill_lines = max(1, int(MEMORY2_MAX_SKILL_LINES))
    cap = max(600, int(MEMORY2_MAX_TOTAL_CHARS))

    # always include top preference/profile; add relevant facts without dupes
    pref_lines = [_line(f"- {f.get('key')}: {f.get('value')}") for f in preferences[:max_fact_lines]]
    prof_lines = [_line(f"- {f.get('key')}: {f.get('value')}") for f in profile[:max_fact_lines]]
    con_lines = [_line(f"- {f.get('key')}: {f.get('value')}") for f in constraints[:max_fact_lines]]
    vol_lines = [_line(f"- {f.get('key')}: {f.get('value')} (expires {f.get('expires_at','soon')})") for f in volatile[:max_fact_lines]]

    seen = {x.lower() for x in pref_lines + prof_lines + con_lines + vol_lines}
    for f in relevant_facts:
        ln = _line(f"- {f.get('key')}: {f.get('value')}")
        if ln.lower() not in seen and len(pref_lines) < max_fact_lines:
            pref_lines.append(ln)
            seen.add(ln.lower())

    skill_lines = []
    for s in relevant_skills[:max_skill_lines]:
        st = "; ".join([str(x) for x in (s.get("steps") or [])[:3]])
        skill_lines.append(_line(f"- {s.get('trigger')}: {st}"))

    def render(vlines: List[str], slines: List[str], clines: List[str], plines: List[str], pflines: List[str]) -> str:
        return "\n".join(
            [
                "MEMORY CONTEXT (authoritative; may be incomplete)",
                "User profile:",
                *(pflines or ["- (none)"]),
                "Preferences:",
                *(plines or ["- (none)"]),
                "Constraints:",
                *(clines or ["- (none)"]),
                "Volatile (expires):",
                *(vlines or ["- (none)"]),
                "Relevant prior solutions:",
                *(slines or ["- (none)"]),
                "Rule: If the user's latest instruction conflicts with memory, follow the latest instruction and update memory.",
            ]
        ).strip()

    block = render(vol_lines, skill_lines, con_lines, pref_lines, prof_lines)
    if len(block) <= cap:
        return block

    # drop in order Volatile -> Skills -> Constraints -> Profile, keep preferences last
    for bucket in ("volatile", "skills", "constraints", "profile"):
        if bucket == "volatile":
            vol_lines = []
        elif bucket == "skills":
            skill_lines = []
        elif bucket == "constraints":
            con_lines = []
        elif bucket == "profile":
            prof_lines = []
        block = render(vol_lines, skill_lines, con_lines, pref_lines, prof_lines)
        if len(block) <= cap:
            return block

    # final clamp by trimming preference lines count
    while len(pref_lines) > 1:
        pref_lines = pref_lines[:-1]
        block = render(vol_lines, skill_lines, con_lines, pref_lines, prof_lines)
        if len(block) <= cap:
            return block
    return block[:cap]
