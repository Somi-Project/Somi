from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

try:
    from .generalsearch import search_general
except Exception:  # pragma: no cover - script mode
    from workshop.toolbox.stacks.web_core.websearch_tools.generalsearch import search_general

_HISTORY_HINTS = (
    "in ", "during ", "as of ", "back in", "historical", "price", "value", "cost", "rate",
    "what was", "how much was", "close price", "open price", "on "
)


def looks_like_historical_query(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", q))
    has_month = bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", q))
    return (has_year or has_month) and any(h in q for h in _HISTORY_HINTS)


def cheap_adequacy_check(query: str, llm_answer: str) -> bool:
    """True means answer is adequate enough to skip historical_search.py fallback."""
    q = (query or "").strip().lower()
    ans = (llm_answer or "").strip()
    ans_l = ans.lower()
    if not ans:
        return False
    if len(ans) < 90:
        return False
    if any(x in ans_l for x in ("i don't know", "not sure", "cannot find", "can't find", "might be")):
        return False
    # For price/value/rate history questions we expect at least one numeric token.
    if any(k in q for k in ("price", "value", "cost", "rate", "how much")):
        if not re.search(r"\$?\d[\d,]*(?:\.\d+)?", ans):
            return False
    # must include temporal anchor if question asks historical date context
    if re.search(r"\b(19|20)\d{2}\b", q) and not re.search(r"\b(19|20)\d{2}\b", ans_l):
        return False
    return True


def sanitize_final_output(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"<\/?think>", "", out, flags=re.IGNORECASE)
    out = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", out)
    out = re.sub(r"(?im)^\s*previous query:.*$", "", out)
    out = re.sub(r"(?im)^\s*previous top result:.*$", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out[:2400].strip()


async def build_historical_answer(query: str) -> str:
    rows = await search_general(query, min_results=3)
    if not rows:
        return "I couldn't find reliable historical sources for that query right now."

    lines: List[str] = []
    for r in rows[:5]:
        title = str(r.get("title") or "Source")
        snippet = str(r.get("description") or "").strip()
        url = str(r.get("url") or "").strip()
        if snippet:
            lines.append(f"- {title}: {snippet}{f' ({url})' if url else ''}")
        elif url:
            lines.append(f"- {title} ({url})")

    lead = "I checked web sources for historical context."
    if any(k in (query or "").lower() for k in ("price", "value", "rate", "cost")):
        lead = "I checked web sources for historical pricing context."

    return sanitize_final_output(f"{lead}\n\n" + "\n".join(lines))


async def maybe_enrich_historical_answer(query: str, llm_answer: str) -> str:
    if not looks_like_historical_query(query):
        return sanitize_final_output(llm_answer)
    if cheap_adequacy_check(query, llm_answer):
        return sanitize_final_output(llm_answer)

    script_path = Path(__file__).resolve()
    proc = await asyncio.create_subprocess_exec(
        "python",
        str(script_path),
        "--query",
        str(query or ""),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        return sanitize_final_output(llm_answer)
    try:
        payload: Dict[str, Any] = json.loads((stdout or b"").decode("utf-8", errors="ignore"))
        synthesized = str(payload.get("answer") or "").strip()
        if synthesized:
            return sanitize_final_output(synthesized)
    except Exception:
        return sanitize_final_output(llm_answer)
    return sanitize_final_output(llm_answer)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Historical query web fallback.")
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    answer = await build_historical_answer(args.query)
    print(json.dumps({"answer": answer}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))


