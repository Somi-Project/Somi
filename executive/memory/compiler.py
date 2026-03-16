from __future__ import annotations

from typing import Iterable, List

from config.memorysettings import (
    MEMORY_LINE_MAX_CHARS,
    MEMORY_MAX_FACT_LINES,
    MEMORY_MAX_PINNED_LINES,
    MEMORY_MAX_SKILL_LINES,
    MEMORY_MAX_TOTAL_CHARS,
)


def _ln(s: str) -> str:
    s = (s or "").strip()
    n = int(MEMORY_LINE_MAX_CHARS)
    return s if len(s) <= n else (s[: n - 3].rstrip() + "...")


def _cut(lines: Iterable[str], n: int) -> List[str]:
    out = []
    for x in lines:
        if len(out) >= n:
            break
        out.append(_ln(x))
    return out


def build_block(pinned: List[str], facts: List[str], skills: List[str], volatile: List[str]) -> str:
    pinned = _cut(pinned, int(MEMORY_MAX_PINNED_LINES))
    facts = _cut(facts, int(MEMORY_MAX_FACT_LINES))
    skills = _cut(skills, int(MEMORY_MAX_SKILL_LINES))
    volatile = _cut(volatile, int(MEMORY_MAX_FACT_LINES))

    def render() -> str:
        return "\n".join(
            [
                "MEMORY CONTEXT (authoritative; may be incomplete)",
                "Pinned:",
                *(pinned or ["- (none)"]),
                "Relevant facts:",
                *(facts or ["- (none)"]),
                "Relevant prior solutions:",
                *(skills or ["- (none)"]),
                "Volatile:",
                *(volatile or ["- (none)"]),
                "Rule: If the user's latest instruction conflicts with memory, follow the latest instruction and update memory.",
            ]
        ).strip()

    block = render()
    cap = int(MEMORY_MAX_TOTAL_CHARS)
    if len(block) <= cap:
        return block

    # drop volatile then facts then skills; keep pinned
    volatile = []
    block = render()
    if len(block) <= cap:
        return block
    while facts and len(block) > cap:
        facts = facts[:-1]
        block = render()
    while skills and len(block) > cap:
        skills = skills[:-1]
        block = render()
    if len(block) > cap:
        block = block[:cap]
    return block
