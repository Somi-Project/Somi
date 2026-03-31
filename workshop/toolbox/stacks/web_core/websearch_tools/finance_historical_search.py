from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List

import httpx

from workshop.toolbox.stacks.research_core.searxng import search_searxng, _tavily_enrich
from workshop.toolbox.stacks.web_core.websearch_tools.search_common import SearchProfile, dedupe_by_url, normalize_search_result

from .ctickers import COMMODITY_TICKER_DICTIONARY
from .ftickers import FOREX_TICKER_DICTIONARY
from .itickers import INDEX_TICKER_DICTIONARY
from .stickers import STOCK_TICKER_DICTIONARY
from .generalsearch import _ddg_text, _normalize_ddg

logger = logging.getLogger(__name__)

FINANCE_HISTORICAL_PROFILE = SearchProfile(
    name="finance_historical",
    category="general",
    time_range="year",
    safe=1,
    domain="finance_historical",
)

_TELEMETRY: Dict[str, int] = {
    "sanitized_query_count": 0,
    "filtered_results_count": 0,
    "fallback_triggered_count": 0,
}
_DIAG_STATE: Dict[str, Any] = {
    "last_log_ts": 0.0,
    "last_snapshot": {k: 0 for k in _TELEMETRY},
}
_DIAG_INTERVAL_S = 300.0

_DEFAULT_BUDGETS_MS: Dict[str, int] = {
    "primary": 3500,
    "fallback": 3500,
    "enrich": 1200,
}

_META_PREFIXES = (
    "previous query:",
    "previous top result:",
    "now answer this follow-up:",
    "you have the previous search results available",
    "decide whether to:",
)

_MONTHS = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}

_PREFERRED_NAME_BY_TICKER = {
    "GC=F": "gold price",
    "CL=F": "WTI crude oil price",
    "BZ=F": "Brent crude oil price",
}


def get_finance_historical_telemetry() -> Dict[str, int]:
    return dict(_TELEMETRY)


def reset_finance_historical_telemetry() -> None:
    for k in _TELEMETRY:
        _TELEMETRY[k] = 0
    _DIAG_STATE["last_log_ts"] = 0.0
    _DIAG_STATE["last_snapshot"] = {k: 0 for k in _TELEMETRY}


def _maybe_emit_diagnostics(now_ts: float | None = None) -> None:
    now = float(now_ts if now_ts is not None else time.time())
    elapsed = now - float(_DIAG_STATE.get("last_log_ts", 0.0))
    if elapsed < _DIAG_INTERVAL_S:
        return
    prev = dict(_DIAG_STATE.get("last_snapshot") or {})
    curr = get_finance_historical_telemetry()
    delta = {k: int(curr.get(k, 0)) - int(prev.get(k, 0)) for k in curr}
    if all(v <= 0 for v in delta.values()):
        return

    spikes = []
    if delta.get("fallback_triggered_count", 0) >= 20:
        spikes.append("fallback_spike")
    if delta.get("filtered_results_count", 0) >= 100:
        spikes.append("filter_spike")

    logger.info(
        "finance_historical_diag interval_s=%.1f totals=%s deltas=%s spikes=%s",
        elapsed,
        curr,
        delta,
        spikes or ["none"],
    )
    _DIAG_STATE["last_log_ts"] = now
    _DIAG_STATE["last_snapshot"] = curr


def strip_meta_scaffold(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""

    m = re.search(r"(?is)now\s+answer\s+this\s+follow-up\s*:\s*(.+)$", raw)
    if m:
        cleaned = m.group(1)
    else:
        lines = []
        for line in raw.splitlines():
            ll = line.strip().lower().lstrip("-â€¢* ")
            if any(ll.startswith(prefix) for prefix in _META_PREFIXES):
                continue
            if ll.startswith("decide whether to"):
                continue
            lines.append(line)
        cleaned = "\n".join(lines)

    cleaned = re.sub(
        r"(?im)^\s*(previous query|previous top result|you have the previous search results available|decide whether to)\s*:?.*$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-")
    if cleaned != raw.strip():
        _TELEMETRY["sanitized_query_count"] += 1
    return cleaned


def _build_reverse_ticker_map() -> Dict[str, str]:
    reverse: Dict[str, str] = {}
    for source in (
        COMMODITY_TICKER_DICTIONARY,
        FOREX_TICKER_DICTIONARY,
        INDEX_TICKER_DICTIONARY,
        STOCK_TICKER_DICTIONARY,
    ):
        for label, ticker in source.items():
            if not ticker:
                continue
            t = str(ticker).strip().upper()
            candidate = str(label).strip().lower()
            if t not in reverse:
                reverse[t] = candidate
            elif "futures" in reverse[t] and "futures" not in candidate:
                reverse[t] = candidate
    return reverse


_REVERSE_TICKERS = _build_reverse_ticker_map()


def ticker_to_human_phrase(ticker: str) -> str:
    t = str(ticker or "").strip().upper()
    if not t:
        return ""
    if t in _PREFERRED_NAME_BY_TICKER:
        return _PREFERRED_NAME_BY_TICKER[t]
    name = _REVERSE_TICKERS.get(t)
    if not name:
        return ticker
    name = re.sub(r"\bfutures\b", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+", " ", name)
    if "price" not in name:
        name = f"{name} price".strip()
    return name


def time_anchor(tc: Dict[str, Any]) -> str:
    kind = str((tc or {}).get("kind") or "").lower()
    if kind == "month":
        month = int(tc.get("month") or 0)
        year = int(tc.get("year") or 0)
        return f"{_MONTHS.get(month, month)} {year}".strip()
    if kind == "year":
        return str(tc.get("year") or "").strip()
    if kind == "date":
        d = tc.get("start")
        return d.isoformat() if isinstance(d, date) else ""
    if kind == "range":
        start = tc.get("start")
        end = tc.get("end")
        if isinstance(start, date) and isinstance(end, date):
            return f"{start.isoformat()} to {end.isoformat()}"
    return ""


def rewrite_historical_query(raw_query: str, *, symbol_hint: str | None, tc: Dict[str, Any]) -> str:
    cleaned = strip_meta_scaffold(raw_query)
    anchor = time_anchor(tc)
    phrase = ticker_to_human_phrase(symbol_hint or "") if symbol_hint else ""

    q = cleaned
    if phrase:
        q = re.sub(re.escape(str(symbol_hint or "")), "", q, flags=re.IGNORECASE).strip() or phrase
    if anchor and anchor.lower() not in q.lower():
        q = f"{q} {anchor}".strip()

    if not phrase and symbol_hint and re.search(r"^[A-Z0-9=\-\.\^]+$", str(symbol_hint)) and symbol_hint not in q:
        tokeny = re.sub(r"[^A-Za-z]+", "", cleaned)
        if not tokeny:
            q = f"{q} {symbol_hint}".strip()

    suffix = "high low open close average -quote -live -chart -tradingview -technical"
    q = f"{q} {suffix}".strip()
    return re.sub(r"\s+", " ", q).strip()


def _score_finance_historical(item: Dict[str, Any], tc: Dict[str, Any]) -> int:
    anchor = time_anchor(tc).lower()
    anchor_year = str(tc.get("year") or "") if isinstance(tc, dict) else ""
    ul = str(item.get("url") or "").lower()
    title = str(item.get("title") or "")
    desc = str(item.get("description") or item.get("snippet") or "")
    blob = f"{title} {desc}".lower()

    score = 0
    if "/history" in ul:
        score += 5
    for good in ("stooq.com", "fred.stlouisfed.org", "eia.gov", "coingecko.com"):
        if good in ul:
            score += 4
    if re.search(r"\d", blob) or any(k in blob for k in ("high", "low", "open", "close", "average")):
        score += 2
    if anchor and anchor in blob:
        score += 3
    elif anchor_year and anchor_year in blob:
        score += 2
    return score


_RANKERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], int]] = {
    "finance_historical": _score_finance_historical,
    "news": lambda item, _tc: int("news" in str(item.get("url") or "").lower()),
    "science": lambda item, _tc: int(any(d in str(item.get("url") or "").lower() for d in ("arxiv.org", "pubmed", "nature.com"))),
}


def rank_results_by_domain(results: List[Dict[str, Any]], domain: str, tc: Dict[str, Any]) -> List[Dict[str, Any]]:
    ranker = _RANKERS.get((domain or "").strip().lower(), _RANKERS["finance_historical"])
    scored = [(ranker(item, tc), item) for item in results if isinstance(item, dict)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


def filter_finance_historical_results(results: List[Dict[str, Any]], tc: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        ul = url.lower()

        if "finance.yahoo.com/quote/" in ul and "/history" not in ul:
            _TELEMETRY["filtered_results_count"] += 1
            continue
        if "tradingview.com" in ul or "binance.com/en/trade/" in ul:
            _TELEMETRY["filtered_results_count"] += 1
            continue

        filtered.append(item)

    ranked = rank_results_by_domain(filtered, "finance_historical", tc)
    return ranked[:6] if len(ranked) >= 6 else ranked


async def _timed(coro, budget_ms: int):
    if budget_ms <= 0:
        return await coro
    return await asyncio.wait_for(coro, timeout=float(budget_ms) / 1000.0)


async def search_finance_historical(
    query: str,
    *,
    min_results: int = 3,
    tc: Dict[str, Any] | None = None,
    budgets_ms: Dict[str, int] | None = None,
) -> List[Dict[str, Any]]:
    cleaned = strip_meta_scaffold(query)
    tc = tc or {}
    budgets = dict(_DEFAULT_BUDGETS_MS)
    if budgets_ms:
        budgets.update({k: int(v) for k, v in budgets_ms.items() if isinstance(v, (int, float))})

    searx_rows: List[Dict[str, Any]] = []
    ddg_rows: List[Dict[str, Any]] = []

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            searx_rows = await _timed(
                search_searxng(
                    client,
                    cleaned,
                    max_results=8,
                    profile=FINANCE_HISTORICAL_PROFILE.name,
                    source_name="searxng",
                    domain=FINANCE_HISTORICAL_PROFILE.domain,
                ),
                budgets.get("primary", 3500),
            )
        except Exception:
            searx_rows = []

        combined = dedupe_by_url([normalize_search_result(r, source="searxng", provider="searxng") for r in searx_rows])
        filtered = filter_finance_historical_results(combined, tc)

        # early exit: enough quality results from primary path
        if len(filtered) >= int(min_results):
            logger.info(
                "finance_historical_search query='%s' primary_ms=%.1f fallback_ms=0 filtered=%d early_exit=true",
                cleaned,
                (time.perf_counter() - t0) * 1000,
                len(filtered),
            )
            _maybe_emit_diagnostics()
            return filtered[:6]

        _TELEMETRY["fallback_triggered_count"] += 1

        # retry with broader profile first
        try:
            broader_rows = await _timed(
                search_searxng(
                    client,
                    cleaned,
                    max_results=10,
                    profile="general",
                    category="general",
                    time_range=None,
                    source_name="searxng",
                    domain="general",
                ),
                budgets.get("fallback", 3500),
            )
        except Exception:
            broader_rows = []

    ddg_rows = _normalize_ddg(await _ddg_text(cleaned, max_results=10)) if len(filtered) < int(min_results) else []

    all_rows = dedupe_by_url(
        [*([normalize_search_result(r, source="searxng", provider="searxng") for r in searx_rows]),
         *([normalize_search_result(r, source="searxng", provider="searxng") for r in (broader_rows or [])]),
         *([normalize_search_result(r, source="ddg", provider="ddg") for r in ddg_rows])]
    )
    filtered = filter_finance_historical_results(all_rows, tc)

    logger.info(
        "finance_historical_search query='%s' searx_raw=%d broader_raw=%d ddg_raw=%d filtered=%d elapsed_ms=%.1f top_urls=%s",
        cleaned,
        len(searx_rows),
        len(broader_rows or []),
        len(ddg_rows),
        len(filtered),
        (time.perf_counter() - t0) * 1000,
        [str(r.get("url") or "") for r in filtered[:6]],
    )

    # Tavily finance enrichment when results remain thin
    if len(filtered) < min_results:
        seen_urls = {str(r.get("url") or "") for r in all_rows if isinstance(r, dict)}
        tavily_rows = await _tavily_enrich(
            query=cleaned,
            max_results=min_results - len(filtered),
            existing_urls=seen_urls,
            domain="finance_historical",
            topic="finance",
        )
        if tavily_rows:
            tavily_norm = [normalize_search_result(r, source="tavily", provider="tavily") for r in tavily_rows]
            all_rows = dedupe_by_url(all_rows + tavily_norm)
            filtered = filter_finance_historical_results(all_rows, tc)
            logger.info(
                "finance_historical_search tavily_enrichment added %d results for '%s'",
                len(tavily_rows), cleaned,
            )

    if len(filtered) >= min_results:
        _maybe_emit_diagnostics()
        return filtered[:6]
    _maybe_emit_diagnostics()
    return all_rows[: max(min_results, 3)]



