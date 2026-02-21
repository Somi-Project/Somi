from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from handlers.websearch_tools.conversion import parse_conversion_request


@dataclass
class RouteDecision:
    route: str  # command|local_memory_intent|conversion_tool|websearch|llm_only
    tool_veto: bool = False
    reason: str = ""
    signals: Dict[str, Any] = field(default_factory=dict)


def _is_command(prompt_l: str) -> bool:
    return prompt_l.strip() in {"stop", "end", "quit", "memory doctor"}


def _is_personal_memory_intent(prompt_l: str) -> bool:
    if re.search(r"\bwhat'?s\s+my\b", prompt_l):
        return True
    if re.search(r"\bmy\s+(name|preferences?|goals?|reminders?|favorite)\b", prompt_l):
        return True
    strong = (
        "remember this", "remember that", "remember about me", "what do you remember",
        "from now on", "my favorite", "favorite drink", "my reminders", "my goals",
    )
    return any(s in prompt_l for s in strong)


def _is_explicit_websearch(prompt_l: str) -> bool:
    return bool(re.search(r"\b(search|look up|google|cite|citation|source|sources|find online|check online)\b", prompt_l))


def _is_volatile_with_strong_signal(prompt_l: str) -> bool:
    # Do not treat plain "now/current/update" as finance or web intent.
    finance_strong = re.search(r"\b(stock|stocks|ticker|share price|market cap|price of\s+\$?[a-z]{1,6}|quote for)\b", prompt_l)
    weather_strong = re.search(r"\b(weather|forecast|temperature|rain|humidity|wind)\b", prompt_l)
    news_strong = re.search(r"\b(news|headlines|breaking news|current events)\b", prompt_l)
    return bool(finance_strong or weather_strong or news_strong)


def decide_route(prompt: str, agent_state: Optional[Dict[str, Any]] = None) -> RouteDecision:
    p = (prompt or "").strip()
    pl = p.lower()

    if _is_command(pl):
        return RouteDecision(route="command", tool_veto=True, reason="hard_command")

    if _is_personal_memory_intent(pl):
        return RouteDecision(route="local_memory_intent", tool_veto=True, reason="personal_memory_intent")

    if parse_conversion_request(p) is not None:
        return RouteDecision(route="conversion_tool", tool_veto=True, reason="parser_confirmed_conversion")

    explicit = _is_explicit_websearch(pl)
    volatile = _is_volatile_with_strong_signal(pl)
    if explicit or volatile:
        return RouteDecision(route="websearch", tool_veto=False, reason="explicit_or_strong_volatile", signals={"explicit": explicit, "volatile": volatile})

    return RouteDecision(route="llm_only", tool_veto=False, reason="default_llm")
