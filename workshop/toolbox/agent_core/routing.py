from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from executive.strategic.routing_adapter import detect_capulet_artifact_type, should_bypass_capulet
from workshop.toolbox.stacks.web_core.websearch_tools.conversion import parse_conversion_request


@dataclass
class RouteDecision:
    route: str  # command|local_memory_intent|image_tool|conversion_tool|websearch|llm_only
    tool_veto: bool = False
    reason: str = ""
    signals: Dict[str, Any] = field(default_factory=dict)


_CURRENCY_CODES = {
    "usd", "eur", "gbp", "jpy", "cad", "aud", "chf", "nzd", "cny", "inr", "ttd",
    "sek", "nok", "dkk", "hkd", "sgd", "mxn", "brl", "zar", "rub", "try",
}


def _is_command(prompt_l: str) -> bool:
    return prompt_l.strip() in {"stop", "end", "quit", "memory doctor"}


def _is_personal_memory_intent(prompt_l: str) -> bool:
    if re.search(r"\bwhat(?:'|\u2019)?s\s+my\b", prompt_l):
        return True
    if re.search(r"\bmy\s+(name|preferences?|goals?|reminders?|favorite)\b", prompt_l):
        return True
    strong = (
        "remember this", "remember that", "remember about me", "what do you remember",
        "from now on", "my favorite", "favorite drink", "my reminders", "my goals", "who am i",
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


def _wants_no_websearch(prompt_l: str) -> bool:
    return any(
        marker in prompt_l
        for marker in (
            "no websearch",
            "without websearch",
            "internal knowledge only",
            "using internal knowledge only",
            "don't search",
            "dont search",
            "no internet",
            "without internet",
        )
    )


def _wants_url_summary(prompt_l: str) -> bool:
    has_url = bool(re.search(r"https?://\S+", prompt_l))
    asks_summary = bool(re.search(r"\b(summarize|summarise|explain|break down|expand on)\b", prompt_l))
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
    return bool(re.search(r"\b(news|latest news|breaking news|headlines|current events|news about)\b", prompt_l))


def _has_forex_markers(prompt_l: str) -> bool:
    if re.search(r"\b(exchange rate|fx|forex|convert|conversion)\b", prompt_l):
        return True

    for m in re.finditer(r"\b([a-z]{3})\s*(?:/|to)\s*([a-z]{3})\b", prompt_l):
        base = m.group(1).lower()
        quote = m.group(2).lower()
        if base in _CURRENCY_CODES and quote in _CURRENCY_CODES:
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
    return bool(re.search(r"\b(price|current price|market price|quote|price of)\b", prompt_l))


def _detect_intent(prompt_l: str) -> str:
    if _has_research_markers(prompt_l):
        return "science"
    if _has_weather_markers(prompt_l):
        return "weather"
    if _has_news_markers(prompt_l):
        return "news"
    if _has_forex_markers(prompt_l):
        return "forex"
    if _has_crypto_markers(prompt_l):
        return "crypto"
    if _has_stock_commodity_markers(prompt_l):
        return "stock/commodity"
    if _has_price_query(prompt_l):
        return "stock/commodity"
    return "general"


def _is_volatile_with_strong_signal(prompt_l: str) -> bool:
    return bool(
        _has_research_markers(prompt_l)
        or _has_weather_markers(prompt_l)
        or _has_news_markers(prompt_l)
        or _has_forex_markers(prompt_l)
        or _has_crypto_markers(prompt_l)
        or _has_stock_commodity_markers(prompt_l)
        or _has_price_query(prompt_l)
    )


def _is_generic_contextual_followup(prompt_l: str) -> bool:
    text = str(prompt_l or "").strip().lower()
    if not text:
        return False

    words = re.findall(r"[a-z0-9']+", text)
    if len(words) > 14:
        return False

    if _is_explicit_websearch(text):
        return False

    has_followup_verb = bool(
        re.search(
            r"\b(more|expand|elaborate|continue|follow\s*-?\s*up|go deeper|drill down|recap|next step|summari[sz]e)\b",
            text,
        )
    )
    has_reference = bool(re.search(r"\b(this|that|those|it|them|same|earlier|previous)\b", text))

    if has_followup_verb and has_reference:
        return True
    if re.search(r"\b(continue|follow\s*-?\s*up)\b", text):
        return True
    return False

def _contextual_followup_route(prompt_l: str, agent_state: Optional[Dict[str, Any]]) -> Optional[RouteDecision]:
    state = agent_state or {}
    if not state.get("has_tool_context") or state.get("force_no_followup_binding"):
        return None

    last_tool = str(state.get("last_tool_type") or "").lower()

    if last_tool == "finance":
        looks_finance_followup = bool(
            _has_price_query(prompt_l)
            or re.search(r"\b(what was|what is|historical|history|in\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{4}))\b", prompt_l)
            or re.search(r"\b(it|its|that|this)\b", prompt_l)
        )
        if looks_finance_followup:
            explicit_subtype = _has_crypto_markers(prompt_l) or _has_forex_markers(prompt_l) or _has_stock_commodity_markers(prompt_l)
            inferred = _detect_intent(prompt_l)
            last_finance_intent = str(state.get("last_finance_intent") or "").strip().lower()
            if (not explicit_subtype) and last_finance_intent in {"crypto", "forex", "stock/commodity"}:
                inferred = last_finance_intent
            elif inferred not in {"crypto", "forex", "stock/commodity"} and last_finance_intent in {"crypto", "forex", "stock/commodity"}:
                inferred = last_finance_intent
            if inferred not in {"crypto", "forex", "stock/commodity"}:
                inferred = "stock/commodity"
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_finance",
                signals={
                    "intent": inferred,
                    "contextual": True,
                    "requires_execution": False,
                    "read_only": True,
                },
            )

    if last_tool == "weather":
        if re.search(r"\b(today|tomorrow|tonight|hourly|weekend|rain|wind|temperature|forecast)\b", prompt_l):
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_weather",
                signals={
                    "intent": "weather",
                    "contextual": True,
                    "requires_execution": False,
                    "read_only": True,
                },
            )

    if last_tool == "news":
        if re.search(r"\b(expand|more|that story|this story|that one|summarize|summarise|open)\b", prompt_l):
            return RouteDecision(
                route="websearch",
                tool_veto=False,
                reason="contextual_followup_news_web",
                signals={
                    "intent": "news",
                    "contextual": True,
                    "requires_execution": False,
                    "read_only": True,
                },
            )

    if _is_generic_contextual_followup(prompt_l):
        inferred = _detect_intent(prompt_l)
        if inferred == "general":
            if last_tool in {"weather", "news"}:
                inferred = last_tool
            elif last_tool == "finance":
                prev = str(state.get("last_finance_intent") or "").strip().lower()
                inferred = prev if prev in {"crypto", "forex", "stock/commodity"} else "stock/commodity"
        return RouteDecision(
            route="websearch",
            tool_veto=False,
            reason="contextual_followup_generic",
            signals={
                "intent": inferred,
                "contextual": True,
                "requires_execution": False,
                "read_only": True,
            },
        )

    return None


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

    if _wants_no_websearch(pl):
        return RouteDecision(
            route="llm_only",
            tool_veto=False,
            reason="user_requested_no_websearch",
            signals={"no_websearch_override": True, "requires_execution": False, "read_only": True},
        )

    if _wants_url_summary(pl):
        return RouteDecision(
            route="websearch",
            tool_veto=False,
            reason="open_url_and_summarize",
            signals={"intent": "general", "requires_execution": False, "read_only": True},
        )

    contextual = _contextual_followup_route(pl, agent_state)
    if contextual is not None:
        return contextual

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
                "intent": intent,
                "requires_execution": False,
                "read_only": True,
            },
        )

    return RouteDecision(route="llm_only", tool_veto=False, reason="default_llm", signals={"requires_execution": False, "read_only": True})





