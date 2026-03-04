from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from executive.strategic.routing_adapter import detect_capulet_artifact_type, should_bypass_capulet
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


def _has_no_websearch_override(prompt_l: str) -> bool:
    blocked_phrases = (
        "no websearch",
        "no web search",
        "do not browse",
        "don't browse",
        "no browsing",
        "internal knowledge only",
        "use internal knowledge only",
        "no internet",
        "offline only",
    )
    return any(phrase in prompt_l for phrase in blocked_phrases)


def _is_url_summarize_request(prompt: str) -> bool:
    p = str(prompt or "")
    pl = p.lower()
    has_url = bool(re.search(r"https?://\S+", p, flags=re.IGNORECASE))
    asks_summary = bool(re.search(r"\b(summarize|summarise|summary|tl;dr)\b", pl))
    return has_url and asks_summary


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


_FX_CODES = {
    "usd", "eur", "gbp", "jpy", "cad", "aud", "nzd", "chf", "cny", "hkd", "sgd", "sek", "nok", "dkk",
    "mxn", "brl", "zar", "try", "inr", "krw", "twd", "thb", "myr", "idr", "php", "vnd", "rub", "pln",
    "czk", "huf", "ron", "ils", "aed", "sar", "qar", "kwd", "bhd", "omr", "jod", "egp", "pkr", "bdt",
    "lkr", "ngn", "ghs", "kes", "ugx", "tzs", "etb", "mad", "dzd", "ttd",
}


def _has_forex_markers(prompt_l: str) -> bool:
    # forex intent words + verified ISO-like currency pairs (avoid false positives like "you to day")
    if re.search(r"\b(exchange rate|fx|forex|convert|conversion|currency pair)\b", prompt_l):
        return True

    for m in re.finditer(r"\b([a-z]{3})\s*(?:/|to)\s*([a-z]{3})\b", prompt_l):
        a = (m.group(1) or "").lower()
        b = (m.group(2) or "").lower()
        if a in _FX_CODES and b in _FX_CODES:
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



def _has_time_constraint_markers(prompt_l: str) -> bool:
    return bool(
        re.search(r"\b(20\d{2}|19\d{2})\b", prompt_l)
        or re.search(r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec)\b", prompt_l)
        or re.search(r"\b(on|between|from)\s+\d{4}-\d{2}-\d{2}\b", prompt_l)
        or "last year" in prompt_l
    )


def _is_contextual_followup(prompt_l: str, agent_state: Optional[Dict[str, Any]]) -> Optional[RouteDecision]:
    st = agent_state or {}
    if bool(st.get("force_no_followup_binding", False)):
        return None
    last_tool = str(st.get("last_tool_type") or "").lower().strip()
    has_ctx = bool(st.get("has_tool_context", False))
    if not has_ctx or not last_tool:
        return None

    # News/web follow-ups like: "expand second one", "that story", "link 2"
    if last_tool in {"news", "general", "science"}:
        if re.search(r"\b(expand|tell me more|more details|open|summarize|summarise|that story|this story|second|third|first|link\s*#?\d+|result\s*#?\d+)\b", prompt_l):
            inferred = "news" if last_tool == "news" else "general"
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_news_web",
                signals={"explicit": False, "volatile": True, "intent": inferred, "followup": True, "requires_execution": False, "read_only": True},
            )

    # Finance follow-up refinements with history/time constraints
    if last_tool == "finance":
        finance_followup_signal = bool(
            _has_price_query(prompt_l)
            or _has_crypto_markers(prompt_l)
            or _has_stock_commodity_markers(prompt_l)
            or _has_forex_markers(prompt_l)
            or re.search(r"\b(what about|how about|and in|then|same asset|same coin|that one|it|its)\b", prompt_l)
            or re.search(r"\bwhat\s+was\s+it\b", prompt_l)
        )
        history_signal = bool(
            _has_time_constraint_markers(prompt_l)
            or re.search(r"\b(ath|all time high|history|historical|high|low|range|close|open)\b", prompt_l)
        )
        spot_price_signal = bool(
            _has_price_query(prompt_l)
            or _has_crypto_markers(prompt_l)
            or _has_stock_commodity_markers(prompt_l)
            or _has_forex_markers(prompt_l)
            or re.search(r"\b(current|now|today|latest|live|spot)\b", prompt_l)
        )
        if finance_followup_signal and (history_signal or spot_price_signal):
            subtype_ctx = str(st.get("last_finance_intent") or "").strip().lower()
            if _has_crypto_markers(prompt_l):
                inferred_intent = "crypto"
            elif _has_forex_markers(prompt_l):
                inferred_intent = "forex"
            elif _has_stock_commodity_markers(prompt_l):
                inferred_intent = "stock/commodity"
            elif _has_price_query(prompt_l) and subtype_ctx in {"crypto", "forex", "stock/commodity"}:
                inferred_intent = subtype_ctx
            elif _has_price_query(prompt_l):
                inferred_intent = "stock/commodity"
            else:
                inferred_intent = subtype_ctx if subtype_ctx in {"crypto", "forex", "stock/commodity"} else "stock/commodity"
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_finance",
                signals={"explicit": False, "volatile": True, "intent": inferred_intent, "followup": True, "requires_execution": False, "read_only": True},
            )

    # Weather terse follow-up refinements
    if last_tool == "weather":
        if re.search(r"\b(tomorrow|hourly|wind|rain|humidity|uv|sunrise|sunset|more details|what about)\b", prompt_l):
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_weather",
                signals={"explicit": False, "volatile": True, "intent": "weather", "followup": True, "requires_execution": False, "read_only": True},
            )

    return None

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
        return RouteDecision(route="command", tool_veto=True, reason="hard_command", signals={"requires_execution": False, "read_only": True})

    if _is_personal_memory_intent(pl):
        return RouteDecision(route="local_memory_intent", tool_veto=True, reason="personal_memory_intent", signals={"requires_execution": False, "read_only": True})

    image_intent = _detect_image_intent(pl)
    if image_intent:
        return RouteDecision(route="image_tool", tool_veto=True, reason="image_intent", signals={"image_intent": image_intent, "requires_execution": False, "read_only": True})

    if parse_conversion_request(p) is not None:
        return RouteDecision(route="conversion_tool", tool_veto=True, reason="parser_confirmed_conversion", signals={"requires_execution": False, "read_only": True})

    if _has_no_websearch_override(pl):
        return RouteDecision(
            route="llm_only",
            tool_veto=True,
            reason="user_requested_no_websearch",
            signals={
                "no_websearch_override": True,
                "requires_execution": False,
                "read_only": True,
            },
        )

    if _is_url_summarize_request(p):
        return RouteDecision(
            route="websearch",
            tool_veto=False,
            reason="open_url_and_summarize",
            signals={"explicit": True, "volatile": True, "intent": "general", "requires_execution": False, "read_only": True},
        )

    contextual = _is_contextual_followup(pl, agent_state)
    if contextual is not None:
        return contextual

    if not should_bypass_capulet(pl):
        capulet_type = detect_capulet_artifact_type(p)
        if capulet_type:
            return RouteDecision(
                route="llm_only",
                tool_veto=True,
                reason="capulet_strategic",
                signals={
                    "capulet_artifact_type": capulet_type,
                    "requires_execution": False,
                    "read_only": True,
                },
            )

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
                "requires_execution": False,
                "read_only": True,
            },
        )

    return RouteDecision(route="llm_only", tool_veto=False, reason="default_llm", signals={"requires_execution": False, "read_only": True})
