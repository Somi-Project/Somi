from __future__ import annotations

from dataclasses import dataclass

from handlers.research.career_profiles import ROLE_PROFILES

INTEREST_SEEDS: dict[str, list[str]] = {
    "gaming": [
        "aim training basics",
        "latency and ping basics",
        "hand posture for long gaming sessions",
    ],
    "anime": [
        "how anime studios organize production",
        "story arcs in shonen series",
        "anime soundtrack composition basics",
    ],
    "cars": [
        "basic maintenance intervals",
        "defensive driving fundamentals",
    ],
    "medicine": [
        "clinical reasoning basics",
        "evidence hierarchy overview",
    ],
}


@dataclass
class RoleContext:
    role: str | None
    nugget_style: str
    topic_seeds: list[str]
    domains: list[str]
    source_allowlist: list[str]
    avoid_topics: list[str]
    growth_frequency_default: str


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        text = str(it or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def resolve_role_context(career_role: str | None, user_interests: list[str] | None) -> RoleContext:
    try:
        role_in = str(career_role).strip() if career_role is not None else None
        profile = ROLE_PROFILES.get(role_in or "", ROLE_PROFILES["General"])

        seeds = list(profile.get("topic_seeds") or [])
        interests = [str(i).strip() for i in (user_interests or []) if str(i).strip()]
        for interest in interests:
            seeds.extend(INTEREST_SEEDS.get(interest.lower(), []))

        seeds = _dedupe_keep_order(seeds)[:120]

        return RoleContext(
            role=role_in if role_in in ROLE_PROFILES else "General",
            nugget_style=str(profile.get("nugget_style") or "fun_fact"),
            topic_seeds=seeds,
            domains=_dedupe_keep_order([str(d) for d in (profile.get("domains") or [])]),
            source_allowlist=_dedupe_keep_order([str(d) for d in (profile.get("source_allowlist") or [])]),
            avoid_topics=_dedupe_keep_order([str(d) for d in (profile.get("avoid_topics") or [])]),
            growth_frequency_default=str(profile.get("growth_frequency_default") or "weekly"),
        )
    except Exception:
        fallback = ROLE_PROFILES["General"]
        return RoleContext(
            role="General",
            nugget_style=str(fallback.get("nugget_style") or "fun_fact"),
            topic_seeds=list(fallback.get("topic_seeds") or []),
            domains=list(fallback.get("domains") or ["general"]),
            source_allowlist=list(fallback.get("source_allowlist") or []),
            avoid_topics=list(fallback.get("avoid_topics") or []),
            growth_frequency_default=str(fallback.get("growth_frequency_default") or "weekly"),
        )
