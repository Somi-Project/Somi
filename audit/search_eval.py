from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workshop.toolbox.stacks.research_core.searxng import search_searxng
from workshop.toolbox.stacks.web_core.websearch import WebSearchHandler
from workshop.toolbox.stacks.web_core.websearch_tools.generalsearch import search_general


@dataclass(frozen=True)
class EvalCase:
    query: str
    kind: str
    must_domains: tuple[str, ...]
    focus_terms: tuple[str, ...]


DEFAULT_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        query="check out openclaw on github",
        kind="github",
        must_domains=("github.com",),
        focus_terms=("openclaw",),
    ),
    EvalCase(
        query="summarize this https://github.com/openclaw/openclaw",
        kind="github",
        must_domains=("github.com",),
        focus_terms=("openclaw",),
    ),
    EvalCase(
        query="what are the latest hypertension guidelines",
        kind="medical_latest",
        must_domains=("acc.org", "heart.org", "ahajournals.org", "escardio.org", "who.int", "nice.org.uk"),
        focus_terms=("hypertension", "guideline"),
    ),
    EvalCase(
        query="latest ACC/AHA hypertension guideline",
        kind="medical_latest",
        must_domains=("acc.org", "heart.org", "ahajournals.org"),
        focus_terms=("acc", "aha", "hypertension", "guideline"),
    ),
    EvalCase(
        query="compare openclaw and deer-flow on github",
        kind="github_compare",
        must_domains=("github.com",),
        focus_terms=("openclaw", "deer-flow"),
    ),
    EvalCase(
        query="what changed in python 3.13 docs",
        kind="docs_change",
        must_domains=("docs.python.org", "github.com"),
        focus_terms=("python", "3.13", "docs"),
    ),
    EvalCase(
        query="latest WHO dengue treatment guidance",
        kind="medical_latest",
        must_domains=("who.int", "paho.org", "cdc.gov"),
        focus_terms=("who", "dengue", "guidance"),
    ),
)

SOMI_TIMEOUT_S = 60.0
GENERAL_TIMEOUT_S = 20.0
SEARX_TIMEOUT_S = 10.0


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _safe(text: Any, limit: int = 220) -> str:
    raw = str(text or "").replace("\r", " ").replace("\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = raw.encode("ascii", "replace").decode("ascii")
    return raw[:limit]


def _describe_rows(rows: Iterable[Dict[str, Any]], limit: int = 5) -> List[str]:
    out: List[str] = []
    for idx, row in enumerate(list(rows)[:limit], start=1):
        if not isinstance(row, dict):
            continue
        out.append(
            f"{idx}. {_safe(row.get('title'), 100)} | {_host(str(row.get('url') or ''))} | "
            f"{_safe(row.get('source') or row.get('provider') or '', 30)} | {_safe(row.get('description'), 180)}"
        )
    return out or ["<no rows>"]


def _blob(rows: Iterable[Dict[str, Any]], report: Dict[str, Any]) -> str:
    parts = [str((report or {}).get("summary") or "")]
    for row in rows:
        if isinstance(row, dict):
            parts.append(str(row.get("title") or ""))
            parts.append(str(row.get("description") or ""))
            parts.append(str(row.get("url") or ""))
    return " ".join(parts).lower()


def _score_case(case: EvalCase, somi_rows: List[Dict[str, Any]], report: Dict[str, Any]) -> tuple[int, List[str]]:
    domains = [_host(str(r.get("url") or "")) for r in somi_rows if isinstance(r, dict)]
    blob = _blob(somi_rows, report)
    mode = str((report or {}).get("mode") or "").strip().lower()
    score = 0
    notes: List[str] = []

    if case.kind.startswith("github"):
        if mode == "github":
            score += 2
        else:
            notes.append("mode_not_github")
        if any("github.com" in d for d in domains):
            score += 2
        else:
            notes.append("no_github_results")
        if "openclaw" in blob:
            score += 1
        else:
            notes.append("missing_openclaw_focus")
        if case.kind == "github_compare":
            if "deer-flow" in blob or "deer flow" in blob:
                score += 1
            else:
                notes.append("missing_deerflow_focus")
        return score, notes

    if case.kind == "docs_change":
        if mode == "deep":
            score += 1
        else:
            notes.append("mode_not_deep")
        if any(d in domains for d in case.must_domains):
            score += 2
        else:
            notes.append("no_python_docs_source")
        if "python" in blob and "3.13" in blob:
            score += 1
        else:
            notes.append("missing_python_3_13_focus")
        if "arxiv.org" not in domains[:3]:
            score += 1
        else:
            notes.append("arxiv_pollution_top3")
        return score, notes

    if case.kind == "medical_latest":
        if mode == "deep":
            score += 1
        else:
            notes.append("mode_not_deep")
        if any(any(must in d for must in case.must_domains) for d in domains[:5]):
            score += 2
        else:
            notes.append("missing_authoritative_domain_top5")
        if all(term in blob for term in case.focus_terms[:2]):
            score += 1
        else:
            notes.append("missing_focus_terms")
        if re.search(r"\b202[4-9]\b", blob):
            score += 1
        else:
            notes.append("missing_recent_year_signal")
        return score, notes

    return score, notes


async def _raw_searx(query: str, category: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        return await search_searxng(
            client,
            query,
            max_results=5,
            max_pages=1,
            profile="science" if category == "science" else "general",
            category=category,
            source_name="searxng_direct",
            domain="biomed" if category == "science" else "general",
        )


def _category_for_query(query: str) -> str:
    ql = str(query or "").lower()
    if any(marker in ql for marker in ("guideline", "guidelines", "who", "treatment", "latest")):
        return "science"
    return "general"


async def _evaluate_case(handler: WebSearchHandler, case: EvalCase) -> Dict[str, Any]:
    category = _category_for_query(case.query)

    somi_rows: List[Dict[str, Any]] = []
    general_rows: List[Dict[str, Any]] = []
    searx_rows: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {}
    somi_error = ""
    general_error = ""
    searx_error = ""

    start = time.perf_counter()
    try:
        somi_rows = await asyncio.wait_for(handler.search(case.query), timeout=SOMI_TIMEOUT_S)
        report = dict(handler.last_browse_report or {})
    except Exception as exc:
        somi_error = f"{type(exc).__name__}: {exc}"
    somi_elapsed = round(time.perf_counter() - start, 2)

    start = time.perf_counter()
    try:
        general_rows = await asyncio.wait_for(search_general(case.query, min_results=3), timeout=GENERAL_TIMEOUT_S)
    except Exception as exc:
        general_error = f"{type(exc).__name__}: {exc}"
    general_elapsed = round(time.perf_counter() - start, 2)

    start = time.perf_counter()
    try:
        searx_rows = await asyncio.wait_for(_raw_searx(case.query, category), timeout=SEARX_TIMEOUT_S)
    except Exception as exc:
        searx_error = f"{type(exc).__name__}: {exc}"
    searx_elapsed = round(time.perf_counter() - start, 2)

    score, notes = _score_case(case, somi_rows, report)
    if somi_error:
        notes.append(f"somi_error:{somi_error.split(':', 1)[0]}")
    if general_error:
        notes.append(f"general_error:{general_error.split(':', 1)[0]}")
    if searx_error:
        notes.append(f"searx_error:{searx_error.split(':', 1)[0]}")

    return {
        "query": case.query,
        "kind": case.kind,
        "somi_time_seconds": somi_elapsed,
        "search_general_time_seconds": general_elapsed,
        "raw_searx_time_seconds": searx_elapsed,
        "browse_mode": str(report.get("mode") or ""),
        "score": score,
        "notes": notes,
        "summary": _safe(report.get("summary"), 420),
        "execution_summary": _safe(report.get("execution_summary"), 260),
        "limitations": [_safe(item, 180) for item in list(report.get("limitations") or [])[:4]],
        "somi_error": _safe(somi_error, 220),
        "general_error": _safe(general_error, 220),
        "searx_error": _safe(searx_error, 220),
        "somi_rows": _describe_rows(somi_rows),
        "search_general_rows": _describe_rows(general_rows),
        "raw_searx_rows": _describe_rows(searx_rows),
    }


def _render_markdown(results: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# Search Eval")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")
    for item in results:
        lines.append(f"## {item['query']}")
        lines.append("")
        lines.append(f"- Kind: {item['kind']}")
        lines.append(f"- Browse mode: {item['browse_mode']}")
        lines.append(f"- Heuristic score: {item['score']}")
        lines.append(f"- Notes: {', '.join(item['notes']) if item['notes'] else 'none'}")
        lines.append(f"- Somi time: {item['somi_time_seconds']}s")
        lines.append(f"- search_general time: {item['search_general_time_seconds']}s")
        lines.append(f"- raw SearXNG time: {item['raw_searx_time_seconds']}s")
        if item["summary"]:
            lines.append(f"- Summary: {item['summary']}")
        if item["execution_summary"]:
            lines.append(f"- Execution summary: {item['execution_summary']}")
        if item["somi_error"]:
            lines.append(f"- Somi error: {item['somi_error']}")
        if item["general_error"]:
            lines.append(f"- search_general error: {item['general_error']}")
        if item["searx_error"]:
            lines.append(f"- raw SearXNG error: {item['searx_error']}")
        if item["limitations"]:
            lines.append("- Limitations:")
            for lim in item["limitations"]:
                lines.append(f"  - {lim}")
        lines.append("- Top Somi rows:")
        for row in item["somi_rows"]:
            lines.append(f"  - {row}")
        lines.append("- Top search_general rows:")
        for row in item["search_general_rows"]:
            lines.append(f"  - {row}")
        lines.append("- Top raw SearXNG rows:")
        for row in item["raw_searx_rows"]:
            lines.append(f"  - {row}")
        lines.append("")

    avg_score = round(sum(int(item.get("score") or 0) for item in results) / max(1, len(results)), 2)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Average heuristic score: {avg_score}")
    strong = [str(item["query"]) for item in results if int(item.get("score") or 0) >= 4]
    weak = [str(item["query"]) for item in results if int(item.get("score") or 0) <= 2]
    lines.append(f"- Stronger queries: {', '.join(strong) if strong else 'none'}")
    lines.append(f"- Weaker queries: {', '.join(weak) if weak else 'none'}")
    lines.append("")
    return "\n".join(lines)


def _load_cases(path: str | None) -> List[EvalCase]:
    if not path:
        return list(DEFAULT_CASES)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: List[EvalCase] = []
    for row in payload:
        cases.append(
            EvalCase(
                query=str(row.get("query") or "").strip(),
                kind=str(row.get("kind") or "general").strip(),
                must_domains=tuple(str(x).strip() for x in list(row.get("must_domains") or [])),
                focus_terms=tuple(str(x).strip() for x in list(row.get("focus_terms") or [])),
            )
        )
    return [case for case in cases if case.query]


async def _main_async(args: argparse.Namespace) -> int:
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    handler = WebSearchHandler()
    cases = _load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]

    results: List[Dict[str, Any]] = []
    output_path = Path(args.output).resolve() if args.output else None

    for case in cases:
        try:
            result = await _evaluate_case(handler, case)
        except Exception as exc:  # pragma: no cover - live eval path
            result = {
                "query": case.query,
                "kind": case.kind,
                "browse_mode": "",
                "score": 0,
                "notes": [f"eval_failed:{type(exc).__name__}"],
                "somi_time_seconds": 0.0,
                "search_general_time_seconds": 0.0,
                "raw_searx_time_seconds": 0.0,
                "summary": _safe(exc, 220),
                "limitations": [],
                "somi_rows": ["<evaluation failed>"],
                "search_general_rows": ["<evaluation failed>"],
                "raw_searx_rows": ["<evaluation failed>"],
            }
        results.append(result)
        if output_path:
            output_path.write_text(_render_markdown(results), encoding="utf-8")

    report = _render_markdown(results)
    if output_path:
        output_path.write_text(report, encoding="utf-8")
    print(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Somi search quality against live queries.")
    parser.add_argument("--output", help="Write markdown report to this path.")
    parser.add_argument("--cases", help="Optional JSON file overriding the default query cases.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of cases to run.")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
