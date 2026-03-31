from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List

import httpx
try:
    from ddgs import DDGS
except Exception:  # pragma: no cover
    from duckduckgo_search import DDGS

from workshop.toolbox.stacks.research_core.searxng import search_searxng
from .search_common import SearchProfile, normalize_search_result, dedupe_by_url

logger = logging.getLogger(__name__)

# --- Tavily opt-in (activated when TAVILY_API_KEY is set) ---
try:
    from config.settings import TAVILY_API_KEY as _TAVILY_API_KEY
except Exception:
    _TAVILY_API_KEY = ""


async def _tavily_text(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    """Run a Tavily general web search in a thread (blocking SDK)."""
    if not _TAVILY_API_KEY:
        return []

    def _run() -> List[Dict[str, Any]]:
        from tavily import TavilyClient
        client = TavilyClient(api_key=_TAVILY_API_KEY)
        resp = client.search(query, max_results=max_results, topic="general")
        return resp.get("results") or []

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:
        logger.debug("Tavily general search failed: %s", exc)
        return []


def _normalize_tavily(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rr = normalize_search_result(r, source="tavily", provider="tavily")
        if rr.get("url"):
            out.append(rr)
    return out

GENERAL_PROFILE = SearchProfile(name="general", category="general", domain="general")

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


def get_general_search_telemetry() -> Dict[str, int]:
    return dict(_TELEMETRY)


def reset_general_search_telemetry() -> None:
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
    curr = get_general_search_telemetry()
    delta = {k: int(curr.get(k, 0)) - int(prev.get(k, 0)) for k in curr}
    if all(v <= 0 for v in delta.values()):
        return

    spikes = []
    if delta.get("fallback_triggered_count", 0) >= 20:
        spikes.append("fallback_spike")
    if delta.get("filtered_results_count", 0) >= 100:
        spikes.append("filter_spike")

    logger.info(
        "general_search_diag interval_s=%.1f totals=%s deltas=%s spikes=%s",
        elapsed,
        curr,
        delta,
        spikes or ["none"],
    )
    _DIAG_STATE["last_log_ts"] = now
    _DIAG_STATE["last_snapshot"] = curr


def _strip_meta_scaffold_query(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    m = re.search(r"(?is)now\s+answer\s+this\s+follow-up\s*:\s*(.+)$", raw)
    if m:
        cleaned = re.sub(r"\s+", " ", m.group(1)).strip()
        if cleaned != raw.strip():
            _TELEMETRY["sanitized_query_count"] += 1
        return cleaned
    lines = []
    for line in raw.splitlines():
        ll = line.strip().lower().lstrip("-â€¢* ")
        if ll.startswith("previous query:") or ll.startswith("previous top result:") or ll.startswith("you have the previous search results available") or ll.startswith("decide whether to:"):
            continue
        lines.append(line)
    cleaned = re.sub(r"\s+", " ", "\n".join(lines)).strip()
    if cleaned != raw.strip():
        _TELEMETRY["sanitized_query_count"] += 1
    return cleaned


def _looks_finance_historical(query: str) -> bool:
    q = str(query or "").lower()
    if not q:
        return False
    has_time = bool(re.search(r"\b(?:19|20)\d{2}\b", q) or re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\b", q))
    has_asset = any(k in q for k in ("price", "historical", "what was", "gold", "oil", "brent", "wti", "bitcoin", "btc", "eth", "forex", "s&p", "sp500"))
    return has_time and has_asset


def _is_junk_result(url: str, title: str, description: str, *, query: str = "") -> bool:
    ul = (url or "").lower()
    blob = f"{title} {description}".lower()
    if "captcha" in blob and "cloudflare" in blob:
        _TELEMETRY["filtered_results_count"] += 1
        return True
    if _looks_finance_historical(query):
        if "finance.yahoo.com/quote/" in ul and "/history" not in ul:
            _TELEMETRY["filtered_results_count"] += 1
            return True
        if "tradingview.com" in ul or "binance.com/en/trade/" in ul:
            _TELEMETRY["filtered_results_count"] += 1
            return True
    return False


async def _ddg_text(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    def _run() -> List[Dict[str, Any]]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        return []


def _normalize_ddg(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rr = normalize_search_result(r, source="ddg", provider="ddg")
        if rr.get("url"):
            out.append(rr)
    return out


async def search_general(
    query: str,
    min_results: int = 3,
    sanitize_query: bool = True,
    budgets_ms: Dict[str, int] | None = None,
    allow_ddg_fallback: bool = True,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if sanitize_query:
        q = _strip_meta_scaffold_query(q)
    if not q:
        return []

    b = {"primary": 3500, "fallback": 3500}
    if budgets_ms:
        b.update({k: int(v) for k, v in budgets_ms.items() if isinstance(v, (int, float))})

    out: List[Dict[str, Any]] = []
    searx_failed = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sx = await asyncio.wait_for(
                search_searxng(client, q, max_results=8, profile=GENERAL_PROFILE.name, category=GENERAL_PROFILE.category, source_name="searxng", domain=GENERAL_PROFILE.domain),
                timeout=b["primary"] / 1000.0,
            )
        for r in sx:
            rr = normalize_search_result(r, source="searxng", provider="searxng")
            if not _is_junk_result(str(rr.get("url") or ""), str(rr.get("title") or ""), str(rr.get("description") or ""), query=q):
                out.append(rr)
    except Exception:
        searx_failed = True

    # --- Tavily parallel path (opt-in) ---
    if _TAVILY_API_KEY:
        tavily_rows = _normalize_tavily(await _tavily_text(q, max_results=10))
        if tavily_rows:
            out = dedupe_by_url([*out, *tavily_rows])
            out = [r for r in out if not _is_junk_result(str(r.get("url") or ""), str(r.get("title") or ""), str(r.get("description") or ""), query=q)]

    if allow_ddg_fallback and (searx_failed or len(out) < int(min_results)):
        _TELEMETRY["fallback_triggered_count"] += 1
        ddg_rows = _normalize_ddg(await _ddg_text(q, max_results=10))
        out = dedupe_by_url([*out, *ddg_rows])
        out = [r for r in out if not _is_junk_result(str(r.get("url") or ""), str(r.get("title") or ""), str(r.get("description") or ""), query=q)]

    _maybe_emit_diagnostics()
    return out



