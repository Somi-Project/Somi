#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import types
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# dependency-light stubs for local simulation environments
if "httpx" not in sys.modules:
    hx = types.ModuleType("httpx")
    class _DummyClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
    hx.AsyncClient = _DummyClient
    sys.modules["httpx"] = hx

if "duckduckgo_search" not in sys.modules:
    ddg = types.ModuleType("duckduckgo_search")
    class _DDGS:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def text(self, *args, **kwargs): return []
    ddg.DDGS = _DDGS
    sys.modules["duckduckgo_search"] = ddg

from handlers.followup_resolver import FollowUpResolver
from handlers.routing import decide_route
from handlers.tool_context import ToolContextStore
from handlers.websearch_tools.finance_historical_search import (
    filter_finance_historical_results,
    rewrite_historical_query,
    strip_meta_scaffold,
)

try:
    from handlers.websearch_tools.finance import FinanceHandler
except Exception:
    FinanceHandler = None


@dataclass
class SimResult:
    user_text: str
    route: str
    reason: str
    rewritten: str = ""
    injected_results: int = 0


def _extract_time_constraint(query: str) -> Dict[str, Any]:
    if FinanceHandler is not None:
        return FinanceHandler()._extract_time_constraint(query) or {}
    q = (query or "").lower()
    mm = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s+(20\d{2}|19\d{2})\b", q)
    month_map = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
    if mm:
        m = month_map[mm.group(1)]
        y = int(mm.group(2))
        start = date(y, m, 1)
        end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
        return {"kind": "month", "year": y, "month": m, "start": start, "end": end}
    y = re.search(r"\bin\s+(20\d{2}|19\d{2})\b", q)
    if y:
        yy = int(y.group(1))
        return {"kind": "year", "year": yy, "start": date(yy, 1, 1), "end": date(yy, 12, 31)}
    return {}


def _resolve_history_symbol(query: str) -> str | None:
    if FinanceHandler is not None:
        return FinanceHandler()._resolve_history_symbol(query)
    q = (query or "").upper()
    if "GC=F" in q or "GOLD" in q:
        return "GC=F"
    if "OIL" in q or "WTI" in q or "BRENT" in q:
        return "CL=F"
    if "BITCOIN" in q or "BTC" in q:
        return "BTC-USD"
    return None


def _mock_web_rows() -> List[Dict[str, str]]:
    return [
        {"title": "Yahoo Quote Card", "url": "https://finance.yahoo.com/quote/GC=F", "description": "live quote card"},
        {"title": "Yahoo Gold History", "url": "https://finance.yahoo.com/quote/GC=F/history", "description": "Nov 2022 high low close 1760"},
        {"title": "FRED series", "url": "https://fred.stlouisfed.org/series/GOLDAMGBD228NLBM", "description": "2022 monthly averages"},
        {"title": "TradingView", "url": "https://www.tradingview.com/symbols/COMEX-GC1!", "description": "chart"},
    ]


async def _simulate_turns(seq: List[str]) -> Dict[str, Any]:
    store = ToolContextStore(ttl_seconds=120)
    resolver = FollowUpResolver()
    summaries: List[SimResult] = []

    store.set("sim", "news", "latest markets news", [
        {"title": "Headline 1", "url": "https://news.example.com/1", "description": "A"},
        {"title": "Headline 2", "url": "https://news.example.com/2", "description": "B"},
    ])

    for text in seq:
        ctx = store.get("sim")
        follow = resolver.resolve(text, ctx)
        routed_text = str(follow.rewritten_query if follow and follow.rewritten_query else text)
        route = decide_route(routed_text, agent_state={"has_tool_context": bool(ctx and ctx.last_results), "last_tool_type": (ctx.last_tool_type if ctx else "")})

        rewritten = ""
        injected = 0

        if "price" in text.lower() and any(x in text.lower() for x in ("nov", "2020", "2021", "2022", "between")):
            tc = _extract_time_constraint(text)
            symbol = _resolve_history_symbol(text)
            rewritten = rewrite_historical_query(text, symbol_hint=symbol, tc=tc)
            filtered = filter_finance_historical_results(_mock_web_rows(), tc)
            injected = len(filtered[:3])
            store.set("sim", "finance", rewritten, filtered[:3], finance_intent="stock/commodity")
        elif follow and follow.action == "open_url_and_summarize":
            store.mark_selected("sim", rank=follow.selected_index, url=follow.selected_url or follow.url)
            injected = 1

        summaries.append(
            SimResult(
                user_text=text,
                route=route.route,
                reason=route.reason,
                rewritten=rewritten,
                injected_results=injected,
            )
        )

    return {
        "turns": [s.__dict__ for s in summaries],
        "last_selected": {
            "index": int((store.get("sim").last_selected_index if store.get("sim") else 0) or 0),
            "url": str((store.get("sim").last_selected_url if store.get("sim") else "") or ""),
        },
    }


def _stress_rewrites(n: int = 50) -> Dict[str, int]:
    assets = ["gold", "gold futures", "GC=F", "price of gold"]
    times = ["nov 2022", "in 2022", "between 2022-11-01 and 2022-11-30"]
    leaks = 0
    for _ in range(n):
        q = f"what was the {random.choice(assets)} price {random.choice(times)}"
        tc = _extract_time_constraint(q)
        symbol = _resolve_history_symbol(q)
        rq = rewrite_historical_query(q, symbol_hint=symbol, tc=tc)
        if symbol and symbol.upper() in rq.upper() and "gold" in q.lower() and "gc=f" not in q.lower():
            leaks += 1
    return {"stress_checked": n, "raw_ticker_leaks": leaks}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seq", nargs="*", default=[])
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()

    seq = args.seq or [
        "what was the price of gold in nov 2022",
        "what was the price of oil in nov 2022",
        "what was bitcoin price in nov 2019",
        "latest world news",
        "summarize the 2nd result",
    ]

    for idx in range(1, max(1, args.rounds) + 1):
        print(f"\n===== SIMULATION ROUND {idx} =====")
        sim = await _simulate_turns(seq)
        stress = _stress_rewrites(50)
        print(json.dumps({
            "round": idx,
            "seq": [strip_meta_scaffold(x) for x in seq],
            "simulation": sim,
            "stress": stress,
        }, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
