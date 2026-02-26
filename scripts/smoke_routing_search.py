#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from handlers.routing import decide_route
from handlers.websearch import WebSearchHandler

PROMPTS = [
    "what’s my name",
    "remember this: I like mango",
    "100 AUD to TTD",
    "weather in Port of Spain today",
    "latest bitcoin price",
    "pmid 32887913 summary",
    "metformin dosing chronic kidney disease guideline",
    "news about NVIDIA this week",
    "site:nih.gov diabetic ketoacidosis management",
    "explain what an arcuate fasciculus lesion does",
    "what is the current exchange rate USD to EUR",
    "tell me a story",
]

INTENTFUL_WEB = {"weather", "news", "science", "stock/commodity", "crypto", "forex"}


def compact_result_info(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"len": 0}
    first = results[0] if isinstance(results[0], dict) else {}
    return {
        "len": len(results),
        "top_category": first.get("category", ""),
        "source": first.get("source", ""),
        "title": first.get("title", ""),
        "url": first.get("url", ""),
        "deroute": bool(first.get("deroute", False)),
    }


def looks_offline(results: list[dict[str, Any]]) -> bool:
    if not results:
        return False
    first = results[0] if isinstance(results[0], dict) else {}
    txt = f"{first.get('title','')} {first.get('description','')}".lower()
    return any(k in txt for k in ["unavailable", "failed", "veto", "timeout", "error"])


async def main() -> int:
    ws = WebSearchHandler()
    failures = 0

    for prompt in PROMPTS:
        decision = decide_route(prompt, agent_state={"mode": "normal"})
        row: dict[str, Any] = {
            "prompt": prompt,
            "route": decision.route,
            "tool_veto": decision.tool_veto,
            "reason": decision.reason,
            "signals.intent": (decision.signals or {}).get("intent", ""),
        }

        if decision.route == "websearch":
            results = await ws.search(
                prompt,
                tool_veto=decision.tool_veto,
                reason=decision.reason,
                signals=decision.signals,
                route_hint=decision.route,
            )
            info = compact_result_info(results)
            row.update({f"web.{k}": v for k, v in info.items()})

            hinted = (decision.signals or {}).get("intent")
            if hinted in INTENTFUL_WEB and info.get("len", 0) == 0 and not looks_offline(results):
                failures += 1
                row["status"] = "FAIL_EMPTY_RESULTS"
            else:
                row["status"] = "OK"
        else:
            row["status"] = "OK"

        print(json.dumps(row, ensure_ascii=False))

    return failures


if __name__ == "__main__":
    rc = asyncio.run(main())
    if rc:
        print(f"smoke failures: {rc}", file=sys.stderr)
    sys.exit(1 if rc else 0)
