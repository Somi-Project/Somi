from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from handlers.websearch_tools.conversion import parse_conversion_request


@dataclass
class RouteDecision:
    route: str  # command|local_memory_intent|image_tool|conversion_tool|websearch|llm_only
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




def _detect_image_intent(prompt_l: str) -> Optional[str]:
    chart_markers = ("chart", "graph", "plot", "bar chart", "bar graph", "line chart")
    comfy_markers = (
        "generate me a picture", "make a pic", "do a pic", "a pic would be nice",
        "generate an image", "create an image", "draw me", "make me an image",
    )
    if any(m in prompt_l for m in chart_markers):
        return "chart"
    if any(m in prompt_l for m in comfy_markers):
        return "comfyui"
    if re.search(r"\b(generate|create|make|draw)\s+(me\s+)?(an?\s+)?(image|picture|pic|photo|artwork|illustration)\b", prompt_l):
        return "comfyui"
    return None


def _is_explicit_websearch(prompt_l: str) -> bool:
    return bool(
        re.search(
            r"\b(search|look up|google|cite|citation|source|sources|find online|check online|verify)\b",
            prompt_l,
        )
    )


# -----------------------------
# Intent detection helpers
# -----------------------------
_RE_PMID = re.compile(r"\bpmid[:\s]*\d{5,9}\b", re.IGNORECASE)
_RE_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
_RE_NCT = re.compile(r"\bnct\d{8}\b", re.IGNORECASE)
_RE_ARXIV = re.compile(r"\barxiv[:\s]*\d{4}\.\d{4,5}\b", re.IGNORECASE)


def _has_research_markers(prompt_l: str) -> bool:
    if _RE_PMID.search(prompt_l) or _RE_DOI.search(prompt_l) or _RE_NCT.search(prompt_l) or _RE_ARXIV.search(prompt_l):
        return True
    if "site:" in prompt_l:
        # often evidence-seeking; also helps avoid finance false positives (SITE token)
        return True
    return bool(
        re.search(
            r"\b("
            r"study|studies|trial|trials|randomized|randomised|rct|rcts|"
            r"meta-analysis|meta analysis|systematic review|systematic reviews|"
            r"guideline|guidelines|consensus|protocol|standard of care|best practice|"
            r"paper|papers|literature|evidence|clinical evidence|"
            r"doi|pmid|arxiv|pubmed|europepmc|clinicaltrials|nct"
            r")\b",
            prompt_l,
        )
    )


def _has_weather_markers(prompt_l: str) -> bool:
    return bool(re.search(r"\b(weather|forecast|temperature|rain|humidity|wind|sunrise|sunset)\b", prompt_l))


def _has_news_markers(prompt_l: str) -> bool:
    # include plain "news" too; otherwise "news" alone can miss
    return bool(re.search(r"\b(news|latest news|breaking news|headlines|current events|news about)\b", prompt_l))


def _has_forex_markers(prompt_l: str) -> bool:
    # forex intent words + common "USD to EUR" style pairs
    if re.search(r"\b(exchange rate|fx|forex|convert|conversion)\b", prompt_l):
        return True
    if re.search(r"\b([a-z]{3})\s*(?:/|to)\s*([a-z]{3})\b", prompt_l):
        return True
    return False


def _has_crypto_markers(prompt_l: str) -> bool:
    return bool(
        re.search(
            r"\b(btc|bitcoin|eth|ethereum|sol|solana|crypto|cryptocurrency|altcoin|memecoin|coin|token)\b",
            prompt_l,
        )
    )


def _has_stock_commodity_markers(prompt_l: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"stock|stocks|ticker|share price|shares|market cap|marketcap|"
            r"gold|silver|oil|brent|wti|"
            r"dxy|nasdaq|dow|s&p|sp500|vix"
            r")\b",
            prompt_l,
        )
    )


def _has_price_query(prompt_l: str) -> bool:
    # “price of X” strongly implies finance/commodities/crypto
    return bool(re.search(r"\b(price|current price|market price|quote|price of)\b", prompt_l))


def _detect_intent(prompt_l: str) -> str:
    """
    Emits intent strings that WebSearchHandler can actually use:
      stock/commodity | crypto | forex | weather | news | science | general
    Priority matters:
      science > weather/news > finance > general
    """
    if _has_research_markers(prompt_l):
        return "science"
    if _has_weather_markers(prompt_l):
        return "weather"
    if _has_news_markers(prompt_l):
        return "news"

    # Finance family (more specific than "finance")
    # If it looks like a conversion or currency pair -> forex
    if _has_forex_markers(prompt_l):
        return "forex"

    # If crypto terms show up -> crypto
    if _has_crypto_markers(prompt_l):
        return "crypto"

    # Stocks/commodities/index terms -> stock/commodity
    if _has_stock_commodity_markers(prompt_l):
        return "stock/commodity"

    # Generic “price/quote” without crypto/forex markers -> treat as stock/commodity
    # (WebSearchHandler can still re-route internally if needed)
    if _has_price_query(prompt_l):
        return "stock/commodity"

    return "general"


def _is_volatile_with_strong_signal(prompt_l: str) -> bool:
    # anything time-sensitive / evidence-bound should use tools
    return bool(
        _has_research_markers(prompt_l)
        or _has_weather_markers(prompt_l)
        or _has_news_markers(prompt_l)
        or _has_forex_markers(prompt_l)
        or _has_crypto_markers(prompt_l)
        or _has_stock_commodity_markers(prompt_l)
        or _has_price_query(prompt_l)
    )


def decide_route(prompt: str, agent_state: Optional[Dict[str, Any]] = None) -> RouteDecision:
    p = (prompt or "").strip()
    pl = p.lower()

    if _is_command(pl):
        return RouteDecision(route="command", tool_veto=True, reason="hard_command")

    if _is_personal_memory_intent(pl):
        return RouteDecision(route="local_memory_intent", tool_veto=True, reason="personal_memory_intent")

    image_intent = _detect_image_intent(pl)
    if image_intent:
        return RouteDecision(route="image_tool", tool_veto=True, reason="image_intent", signals={"image_intent": image_intent})

    if parse_conversion_request(p) is not None:
        return RouteDecision(route="conversion_tool", tool_veto=True, reason="parser_confirmed_conversion")

    explicit = _is_explicit_websearch(pl)
    volatile = _is_volatile_with_strong_signal(pl)

    if explicit or volatile:
        intent = _detect_intent(pl)
        return RouteDecision(
            route="websearch",
            tool_veto=False,
            reason="explicit_or_strong_volatile",
            signals={
                "explicit": explicit,
                "volatile": volatile,
                "intent": intent,  # <-- matches WebSearchHandler categories
            },
        )

    return RouteDecision(route="llm_only", tool_veto=False, reason="default_llm")
