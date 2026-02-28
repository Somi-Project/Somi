from __future__ import annotations


def should_force_research_websearch(route: str, artifact_intent: str | None, *, enabled: bool) -> bool:
    return bool(enabled and artifact_intent == "research_brief" and str(route or "") != "websearch")


def apply_research_degrade_notice(content: str, *, reason: str = "", enabled: bool = False) -> str:
    if not bool(enabled):
        return content
    reason_l = str(reason or "").lower()
    if "insufficient_sources" not in reason_l and "web search unavailable" not in reason_l:
        return content
    return (content or "").rstrip() + "\n\nI couldn’t fetch enough sources right now, so I answered without citations."
