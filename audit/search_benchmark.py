from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.safe_search_corpus import BenchmarkCase, build_named_corpus, slice_cases
from workshop.toolbox.stacks.research_core.searxng import search_searxng
from workshop.toolbox.stacks.web_core.websearch import WebSearchHandler
from workshop.toolbox.stacks.web_core.websearch_tools.generalsearch import search_general

SOMI_TIMEOUT_S = 60.0
GENERAL_TIMEOUT_S = 20.0
SEARX_TIMEOUT_S = 10.0
CHILD_TIMEOUT_BUFFER_S = 10.0


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _is_timeout_like_exception(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in name


async def _await_quietly(awaitable: Any) -> Any:
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return await awaitable


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


def _extract_child_result(stdout: str) -> Dict[str, Any]:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        start = line.find("{")
        end = line.rfind("}")
        if start < 0 or end <= start:
            continue
        candidate = line[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict) and any(key in parsed for key in ("query", "score", "notes", "somi_rows")):
            return parsed
    raise ValueError("child_no_json_payload")


def _result_needs_inprocess_recovery(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    somi_error = str(result.get("somi_error") or "").strip()
    notes = [str(note or "").strip().lower() for note in (result.get("notes") or [])]
    browse_mode = str(result.get("browse_mode") or "").strip().lower()
    rows = [str(row or "").strip() for row in (result.get("somi_rows") or [])]
    score = int(result.get("score") or 0)

    if somi_error:
        return True
    if any(note.startswith("somi_error:") for note in notes):
        return True
    if score <= 0 and any(note == "no_rows" for note in notes):
        return True
    if not browse_mode and rows[:1] == ["<no rows>"]:
        return True
    return False


def _blob(rows: Iterable[Dict[str, Any]], report: Dict[str, Any]) -> str:
    parts = [str((report or {}).get("summary") or "")]
    for row in rows:
        if isinstance(row, dict):
            parts.extend((str(row.get("title") or ""), str(row.get("description") or ""), str(row.get("url") or "")))
    return " ".join(parts).lower()


def _focus_terms_satisfied(case: BenchmarkCase, *, blob: str, domains: List[str], mode: str) -> bool:
    if not case.focus_terms:
        return True
    focus_terms = list(case.focus_terms[:3])
    threshold = max(1, min(2, len(case.focus_terms)))
    hits = len([term for term in focus_terms if term in blob])
    if hits >= threshold:
        return True

    if case.kind == "finance" and mode in {"stock/commodity", "crypto", "forex"}:
        if any(domain.endswith("finance.yahoo.com") or "finance.yahoo.com" in domain for domain in domains[:3]):
            return True

    if case.kind == "weather" and mode == "weather":
        if any("open-meteo.com" in domain for domain in domains[:3]):
            return True

    if case.kind == "news":
        ai_aliases = (" ai ", "ai ", " ai", "openai", "copilot", "chatgpt", "anthropic")
        if {"artificial", "intelligence"}.issubset(set(case.focus_terms)) and any(alias in f" {blob} " for alias in ai_aliases):
            return True

    return False


def _category_for_query(query: str) -> str:
    ql = str(query or "").lower()
    if any(marker in ql for marker in ("guideline", "guidelines", "who", "treatment", "latest")):
        return "science"
    return "general"


def _intent_hint_for_case(case: BenchmarkCase) -> str:
    kind = str(case.kind or "").strip().lower()
    ql = str(case.query or "").lower()
    if kind == "weather":
        return "weather"
    if kind == "news":
        return "news"
    if kind == "finance":
        if any(token in ql for token in ("bitcoin", "ethereum", "solana", "btc", "eth")):
            return "crypto"
        if any(token in ql for token in ("stock", "stocks", "share price", "ticker", "market cap", "quote")):
            return "stock/commodity"
        if "exchange rate" in ql or "forex" in ql or re.search(r"\b[a-z]{3}\s*(?:/|to)\s*[a-z]{3}\b", ql):
            return "forex"
        return "stock/commodity"
    return ""


def _canonical_news_benchmark_query(query: str) -> str:
    q = " ".join(str(query or "").split()).strip()
    if not q:
        return ""
    patterns = (
        r"^latest\s+(.+?)\s+news$",
        r"^(.+?)\s+headlines today$",
        r"^what happened with\s+(.+?)\s+today$",
        r"^recent\s+(.+?)\s+news update$",
        r"^top\s+(.+?)\s+stories right now$",
    )
    for pattern in patterns:
        match = re.match(pattern, q, re.IGNORECASE)
        if match:
            topic = str(match.group(1) or "").strip()
            if topic:
                return f"{topic} headlines today"
    return q


def _score_case(case: BenchmarkCase, somi_rows: List[Dict[str, Any]], report: Dict[str, Any]) -> tuple[int, List[str]]:
    domains = [_host(str(row.get("url") or "")) for row in somi_rows if isinstance(row, dict)]
    blob = _blob(somi_rows, report)
    mode = str((report or {}).get("mode") or "").strip().lower()
    score = 0
    notes: List[str] = []

    if somi_rows:
        score += 2
    else:
        notes.append("no_rows")

    if case.expected_modes:
        if mode in case.expected_modes:
            score += 1
        else:
            notes.append(f"mode_not_{'/'.join(case.expected_modes)}")
    elif mode:
        score += 1

    if case.must_domains:
        if any(any(must in domain for must in case.must_domains) for domain in domains[:5]):
            score += 1
        else:
            notes.append("missing_expected_domain_top5")

    if case.focus_terms:
        if _focus_terms_satisfied(case, blob=blob, domains=domains, mode=mode):
            score += 1
        else:
            notes.append("missing_focus_terms")

    if case.kind == "medical_latest":
        if re.search(r"\b202[4-9]\b", blob):
            score += 1
        else:
            notes.append("missing_recent_year_signal")

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


async def _evaluate_case(
    case: BenchmarkCase,
    *,
    include_baselines: bool = False,
    somi_timeout_s: float = SOMI_TIMEOUT_S,
    general_timeout_s: float = GENERAL_TIMEOUT_S,
    searx_timeout_s: float = SEARX_TIMEOUT_S,
) -> Dict[str, Any]:
    category = _category_for_query(case.query)
    handler = WebSearchHandler()
    intent_hint = _intent_hint_for_case(case)

    somi_rows: List[Dict[str, Any]] = []
    general_rows: List[Dict[str, Any]] = []
    searx_rows: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {}
    somi_error = ""
    general_error = ""
    searx_error = ""
    general_elapsed = 0.0
    searx_elapsed = 0.0
    recovery_notes: List[str] = []

    started = time.perf_counter()
    try:
        if str(case.kind or "").lower() == "news":
            news_query = _canonical_news_benchmark_query(case.query)
            news_timeout_s = max(4.0, min(float(somi_timeout_s), 15.0))
            try:
                somi_rows = await _await_quietly(
                    asyncio.wait_for(
                        handler._news_lookup_browse(news_query, retries=1, backoff_factor=0.1),
                        timeout=news_timeout_s,
                    )
                )
            except Exception:
                somi_rows = []
            if not somi_rows:
                try:
                    somi_rows = await _await_quietly(
                        asyncio.wait_for(
                            handler._news_lookup_browse(news_query, retries=1, backoff_factor=0.1),
                            timeout=news_timeout_s,
                        )
                    )
                except Exception:
                    somi_rows = []
            report = {
                "mode": "news",
                "execution_summary": "1. Route -> direct benchmark via Somi news shortlist path",
            }
        elif str(case.kind or "").lower() == "weather":
            somi_rows = await _await_quietly(
                asyncio.wait_for(
                    handler.weather_handler.search_weather(case.query),
                    timeout=max(1.0, float(somi_timeout_s)),
                )
            )
            report = {
                "mode": "weather",
                "execution_summary": "1. Route -> direct benchmark via weather handler",
            }
        elif str(case.kind or "").lower() == "finance" and intent_hint in {"stock/commodity", "crypto", "forex"}:
            somi_rows = await _await_quietly(
                asyncio.wait_for(
                    handler._search_finance_intent(intent_hint, case.query),
                    timeout=max(1.0, float(somi_timeout_s)),
                )
            )
            report = {
                "mode": intent_hint,
                "execution_summary": f"1. Route -> direct benchmark via {intent_hint} handler",
            }
        else:
            kind_lower = str(case.kind or "").lower()
            retry_on_empty_kinds = {"general", "general_factual", "general_latest", "medical_latest"}
            retry_attempts = 2 if kind_lower not in {"news", "weather", "finance"} else 1
            recovered_after_retry = False
            last_retry_exc: Exception | None = None
            for attempt_index in range(retry_attempts):
                try:
                    somi_rows = await _await_quietly(
                        asyncio.wait_for(
                            handler.search(case.query, intent_hint=intent_hint),
                            timeout=max(1.0, float(somi_timeout_s)),
                        )
                    )
                    report = dict(handler.last_browse_report or {})
                    if somi_rows or kind_lower not in retry_on_empty_kinds or attempt_index + 1 >= retry_attempts:
                        recovered_after_retry = recovered_after_retry or attempt_index > 0
                        break
                    recovered_after_retry = True
                except Exception as exc:
                    report = dict(handler.last_browse_report or {})
                    last_retry_exc = exc
                    if attempt_index + 1 < retry_attempts and _is_timeout_like_exception(exc):
                        recovered_after_retry = True
                        continue
                    raise
            else:
                if last_retry_exc is not None:
                    raise last_retry_exc
            if recovered_after_retry and somi_rows:
                recovery_notes.append("somi_retry_recovered")
    except Exception as exc:
        somi_error = f"{type(exc).__name__}: {exc}"
    somi_elapsed = round(time.perf_counter() - started, 2)

    if include_baselines:
        started = time.perf_counter()
        try:
            general_rows = await _await_quietly(
                asyncio.wait_for(search_general(case.query, min_results=3), timeout=max(1.0, float(general_timeout_s)))
            )
        except Exception as exc:
            general_error = f"{type(exc).__name__}: {exc}"
        general_elapsed = round(time.perf_counter() - started, 2)

        started = time.perf_counter()
        try:
            searx_rows = await _await_quietly(
                asyncio.wait_for(_raw_searx(case.query, category), timeout=max(1.0, float(searx_timeout_s)))
            )
        except Exception as exc:
            searx_error = f"{type(exc).__name__}: {exc}"
        searx_elapsed = round(time.perf_counter() - started, 2)
    else:
        general_rows = [{"title": "skipped", "url": "", "description": "baseline comparison disabled"}]
        searx_rows = [{"title": "skipped", "url": "", "description": "baseline comparison disabled"}]

    score, notes = _score_case(case, somi_rows, report)
    notes.extend(recovery_notes)
    if somi_error:
        notes.append(f"somi_error:{somi_error.split(':', 1)[0]}")
    if include_baselines and general_error:
        notes.append(f"general_error:{general_error.split(':', 1)[0]}")
    if include_baselines and searx_error:
        notes.append(f"searx_error:{searx_error.split(':', 1)[0]}")

    return {
        "query": case.query,
        "kind": case.kind,
        "compare_baselines": bool(include_baselines),
        "expected_modes": list(case.expected_modes),
        "browse_mode": str(report.get("mode") or ""),
        "score": score,
        "notes": notes,
        "somi_time_seconds": somi_elapsed,
        "search_general_time_seconds": general_elapsed,
        "raw_searx_time_seconds": searx_elapsed,
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


def _summary_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    avg_score = round(sum(int(item.get("score") or 0) for item in results) / max(1, len(results)), 2)
    avg_time = round(sum(float(item.get("somi_time_seconds") or 0.0) for item in results) / max(1, len(results)), 2)
    kinds = sorted({str(item.get("kind") or "") for item in results})
    kind_rows: List[Dict[str, Any]] = []
    for kind in kinds:
        rows = [item for item in results if str(item.get("kind") or "") == kind]
        kind_score = round(sum(int(item.get("score") or 0) for item in rows) / max(1, len(rows)), 2)
        kind_errors = sum(1 for item in rows if item.get("somi_error"))
        kind_rows.append(
            {
                "kind": kind,
                "count": len(rows),
                "avg_score": kind_score,
                "somi_errors": kind_errors,
            }
        )
    return {
        "total_queries": len(results),
        "avg_score": avg_score,
        "avg_time_seconds": avg_time,
        "per_kind": kind_rows,
    }


def _render_summary_markdown(results: List[Dict[str, Any]], *, corpus_name: str, include_title: bool = True) -> str:
    stats = _summary_stats(results)
    lines: List[str] = []
    if include_title:
        lines.extend(["# Search Benchmark Summary", ""])
    lines.extend([f"Generated: {datetime.now().isoformat()}", f"Corpus: {corpus_name}", ""])
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total queries: {stats['total_queries']}")
    lines.append(f"- Average heuristic score: {stats['avg_score']}")
    lines.append(f"- Average Somi time: {stats['avg_time_seconds']}s")
    for item in list(stats.get("per_kind") or []):
        lines.append(
            f"- {item['kind']}: count={item['count']}, avg_score={item['avg_score']}, somi_errors={item['somi_errors']}"
        )
    lines.append("")
    return "\n".join(lines)


def _render_markdown(results: List[Dict[str, Any]], *, corpus_name: str) -> str:
    lines = ["# Search Benchmark", "", f"Generated: {datetime.now().isoformat()}", f"Corpus: {corpus_name}", ""]
    for item in results:
        lines.append(f"## {item['query']}")
        lines.append("")
        lines.append(f"- Kind: {item['kind']}")
        lines.append(f"- Browse mode: {item['browse_mode']}")
        lines.append(f"- Heuristic score: {item['score']}")
        lines.append(f"- Notes: {', '.join(item['notes']) if item['notes'] else 'none'}")
        lines.append(f"- Somi time: {item['somi_time_seconds']}s")
        if item["summary"]:
            lines.append(f"- Summary: {item['summary']}")
        if item["execution_summary"]:
            lines.append(f"- Execution summary: {item['execution_summary']}")
        if item["somi_error"]:
            lines.append(f"- Somi error: {item['somi_error']}")
        lines.append("- Top Somi rows:")
        for row in item["somi_rows"]:
            lines.append(f"  - {row}")
        lines.append("")

    lines.append(_render_summary_markdown(results, corpus_name=corpus_name, include_title=False))
    return "\n".join(lines)


def _load_cases(path: str | None, corpus_name: str) -> List[BenchmarkCase]:
    if not path:
        return build_named_corpus(corpus_name)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        BenchmarkCase(
            query=str(row.get("query") or "").strip(),
            kind=str(row.get("kind") or "general").strip(),
            must_domains=tuple(str(x).strip() for x in list(row.get("must_domains") or [])),
            focus_terms=tuple(str(x).strip().lower() for x in list(row.get("focus_terms") or [])),
            expected_modes=tuple(str(x).strip().lower() for x in list(row.get("expected_modes") or [])),
        )
        for row in payload
        if str((row or {}).get("query") or "").strip()
    ]


def _read_jsonl(path: Path | None) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(dict(json.loads(line)))
            except Exception:
                continue
    return rows


def _append_jsonl(path: Path | None, row: Dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_markdown(path: Path | None, results: List[Dict[str, Any]], *, corpus_name: str) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_markdown(results, corpus_name=corpus_name), encoding="utf-8")


def _write_summary_markdown(path: Path | None, results: List[Dict[str, Any]], *, corpus_name: str) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_summary_markdown(results, corpus_name=corpus_name), encoding="utf-8")


def _finalize_exit(code: int, *, hard_exit: bool = False) -> int:
    if not hard_exit:
        return int(code)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(int(code))
    return int(code)


def _failed_result(case: BenchmarkCase, *, note: str, detail: str = "") -> Dict[str, Any]:
    return {
        "query": case.query,
        "kind": case.kind,
        "expected_modes": list(case.expected_modes),
        "browse_mode": "",
        "score": 0,
        "notes": [note],
        "somi_time_seconds": 0.0,
        "search_general_time_seconds": 0.0,
        "raw_searx_time_seconds": 0.0,
        "summary": _safe(detail, 220),
        "execution_summary": "",
        "limitations": [],
        "somi_error": _safe(detail, 220),
        "general_error": "",
        "searx_error": "",
        "somi_rows": ["<evaluation failed>"],
        "search_general_rows": ["<evaluation failed>"],
        "raw_searx_rows": ["<evaluation failed>"],
    }


async def _single_case_from_stdin() -> int:
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        payload = dict(json.loads(sys.stdin.read() or "{}"))
        compare_baselines = bool(payload.get("compare_baselines"))
        somi_timeout_s = float(payload.get("somi_timeout") or SOMI_TIMEOUT_S)
        general_timeout_s = float(payload.get("general_timeout") or GENERAL_TIMEOUT_S)
        searx_timeout_s = float(payload.get("searx_timeout") or SEARX_TIMEOUT_S)
        case = BenchmarkCase(
            query=str(payload.get("query") or "").strip(),
            kind=str(payload.get("kind") or "general").strip(),
            must_domains=tuple(str(x).strip() for x in list(payload.get("must_domains") or [])),
            focus_terms=tuple(str(x).strip().lower() for x in list(payload.get("focus_terms") or [])),
            expected_modes=tuple(str(x).strip().lower() for x in list(payload.get("expected_modes") or [])),
        )
    except Exception as exc:
        print(json.dumps({"error": f"invalid_case:{type(exc).__name__}"}))
        return 2
    print(
        json.dumps(
            await _evaluate_case(
                case,
                include_baselines=compare_baselines,
                somi_timeout_s=somi_timeout_s,
                general_timeout_s=general_timeout_s,
                searx_timeout_s=searx_timeout_s,
            ),
            ensure_ascii=False,
        )
    )
    return 0


def _run_case_isolated(
    case: BenchmarkCase,
    *,
    timeout_s: float,
    retries: int = 1,
    include_baselines: bool = False,
    somi_timeout_s: float = SOMI_TIMEOUT_S,
    general_timeout_s: float = GENERAL_TIMEOUT_S,
    searx_timeout_s: float = SEARX_TIMEOUT_S,
    allow_inprocess_fallback: bool = True,
) -> Dict[str, Any]:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--single-case-stdin"]
    attempts = max(0, int(retries)) + 1
    required_timeout = max(1.0, float(somi_timeout_s)) + CHILD_TIMEOUT_BUFFER_S
    if include_baselines:
        required_timeout += max(0.0, float(general_timeout_s)) + max(0.0, float(searx_timeout_s))
    payload = json.dumps(
        {
            "query": case.query,
            "kind": case.kind,
            "must_domains": list(case.must_domains),
            "focus_terms": list(case.focus_terms),
            "expected_modes": list(case.expected_modes),
            "compare_baselines": bool(include_baselines),
            "somi_timeout": float(somi_timeout_s),
            "general_timeout": float(general_timeout_s),
            "searx_timeout": float(searx_timeout_s),
        },
        ensure_ascii=False,
    )
    last_note = "child_unexpected_exit"
    last_detail = "isolated runner exhausted retries"

    for attempt in range(attempts):
        current_timeout = max(float(timeout_s), required_timeout) + (attempt * 30.0)
        try:
            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=current_timeout,
                cwd=str(REPO_ROOT),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            last_note = "child_timeout"
            last_detail = str(exc.stderr or exc.stdout or exc)
            if attempt + 1 < attempts:
                continue
            break
        except Exception as exc:
            last_note = f"child_failed:{type(exc).__name__}"
            last_detail = str(exc)
            break

        if proc.returncode != 0:
            last_note = f"child_exit:{proc.returncode}"
            last_detail = str(proc.stderr or "").strip()
            if attempt + 1 < attempts:
                continue
            break
        if not str(proc.stdout or "").strip():
            last_note = "child_no_output"
            last_detail = str(proc.stderr or "").strip()
            if attempt + 1 < attempts:
                continue
            break
        try:
            result = dict(_extract_child_result(proc.stdout or ""))
        except Exception as exc:
            last_note = f"child_json_error:{type(exc).__name__}"
            last_detail = str(proc.stdout or "").strip()[-220:] or str(exc)
            if attempt + 1 < attempts:
                continue
            break
        if allow_inprocess_fallback and _result_needs_inprocess_recovery(result):
            try:
                recovered = dict(
                    asyncio.run(
                        _evaluate_case(
                            case,
                            include_baselines=include_baselines,
                            somi_timeout_s=somi_timeout_s,
                            general_timeout_s=general_timeout_s,
                            searx_timeout_s=searx_timeout_s,
                        )
                    )
                )
            except Exception:
                recovered = {}
            if recovered and (
                int(recovered.get("score") or 0) > int(result.get("score") or 0)
                or (not str(recovered.get("somi_error") or "").strip() and str(result.get("somi_error") or "").strip())
            ):
                notes = list(recovered.get("notes") or [])
                recovered["notes"] = ["isolated_child_result_recovered", *notes]
                if attempt:
                    recovered["notes"] = ["child_retry_recovered", *list(recovered.get("notes") or [])]
                return recovered
        if attempt:
            notes = list(result.get("notes") or [])
            result["notes"] = ["child_retry_recovered", *notes]
        return result

    if not allow_inprocess_fallback:
        return _failed_result(case, note=last_note, detail=last_detail)

    try:
        recovered = dict(
            asyncio.run(
                _evaluate_case(
                    case,
                    include_baselines=include_baselines,
                    somi_timeout_s=somi_timeout_s,
                    general_timeout_s=general_timeout_s,
                    searx_timeout_s=searx_timeout_s,
                )
            )
        )
        notes = list(recovered.get("notes") or [])
        recovered["notes"] = ["isolated_fallback_inprocess", *notes]
        return recovered
    except Exception as exc:
        return _failed_result(case, note=last_note, detail=last_detail or str(exc))


async def _main_async(args: argparse.Namespace) -> int:
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = slice_cases(_load_cases(args.cases, args.corpus), limit=args.limit, chunk_size=args.chunk_size, chunk_index=args.chunk_index)
    output_path = Path(args.output).resolve() if args.output else None
    json_output_path = Path(args.json_output).resolve() if args.json_output else None
    summary_output_path = Path(args.summary_output).resolve() if args.summary_output else None
    existing_by_query = {str(row.get("query") or "").strip(): row for row in _read_jsonl(json_output_path)} if args.resume else {}
    results = list(existing_by_query.values())
    save_every = max(1, int(args.save_every or 1))

    for index, case in enumerate(cases, start=1):
        if case.query in existing_by_query:
            continue
        try:
            result = await _evaluate_case(
                case,
                include_baselines=bool(args.compare_baselines),
                somi_timeout_s=float(args.somi_timeout),
                general_timeout_s=float(args.general_timeout),
                searx_timeout_s=float(args.searx_timeout),
            )
        except Exception as exc:
            result = _failed_result(case, note=f"eval_failed:{type(exc).__name__}", detail=str(exc))
        results.append(result)
        existing_by_query[case.query] = result
        _append_jsonl(json_output_path, result)
        if output_path and index % save_every == 0:
            ordered = [existing_by_query[case_.query] for case_ in cases if case_.query in existing_by_query]
            _write_markdown(output_path, ordered, corpus_name=args.corpus)
            _write_summary_markdown(summary_output_path, ordered, corpus_name=args.corpus)

    ordered = [existing_by_query[case.query] for case in cases if case.query in existing_by_query] if existing_by_query else results
    _write_markdown(output_path, ordered, corpus_name=args.corpus)
    _write_summary_markdown(summary_output_path, ordered, corpus_name=args.corpus)
    if args.stdout_summary_only:
        print(_render_summary_markdown(ordered, corpus_name=args.corpus))
    elif not args.no_stdout_report:
        print(_render_markdown(ordered, corpus_name=args.corpus))
    return 0


def _main_isolated(args: argparse.Namespace) -> int:
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = slice_cases(_load_cases(args.cases, args.corpus), limit=args.limit, chunk_size=args.chunk_size, chunk_index=args.chunk_index)
    output_path = Path(args.output).resolve() if args.output else None
    json_output_path = Path(args.json_output).resolve() if args.json_output else None
    summary_output_path = Path(args.summary_output).resolve() if args.summary_output else None
    existing_by_query = {str(row.get("query") or "").strip(): row for row in _read_jsonl(json_output_path)} if args.resume else {}
    save_every = max(1, int(args.save_every or 1))

    for index, case in enumerate(cases, start=1):
        if case.query in existing_by_query:
            continue
        existing_by_query[case.query] = _run_case_isolated(
            case,
            timeout_s=args.per_case_timeout,
            retries=args.child_retries,
            include_baselines=bool(args.compare_baselines),
            somi_timeout_s=float(args.somi_timeout),
            general_timeout_s=float(args.general_timeout),
            searx_timeout_s=float(args.searx_timeout),
            allow_inprocess_fallback=not bool(args.no_inprocess_fallback),
        )
        _append_jsonl(json_output_path, existing_by_query[case.query])
        if output_path and index % save_every == 0:
            ordered = [existing_by_query[case_.query] for case_ in cases if case_.query in existing_by_query]
            _write_markdown(output_path, ordered, corpus_name=args.corpus)
            _write_summary_markdown(summary_output_path, ordered, corpus_name=args.corpus)

    ordered = [existing_by_query[case.query] for case in cases if case.query in existing_by_query]
    _write_markdown(output_path, ordered, corpus_name=args.corpus)
    _write_summary_markdown(summary_output_path, ordered, corpus_name=args.corpus)
    if args.stdout_summary_only:
        print(_render_summary_markdown(ordered, corpus_name=args.corpus))
    elif not args.no_stdout_report:
        print(_render_markdown(ordered, corpus_name=args.corpus))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run resumable safe search benchmarks against Somi.")
    parser.add_argument("--output", help="Write markdown report to this path.")
    parser.add_argument("--json-output", help="Write JSONL results to this path.")
    parser.add_argument("--summary-output", help="Write a compact markdown summary to this path.")
    parser.add_argument("--cases", help="Optional JSON file overriding the named corpus.")
    parser.add_argument("--corpus", default="default", help="Named corpus: default, research50, everyday250, everyday1000.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit after corpus selection.")
    parser.add_argument("--chunk-size", type=int, default=0, help="Optional chunk size for large corpora.")
    parser.add_argument("--chunk-index", type=int, default=0, help="Zero-based chunk index for chunked runs.")
    parser.add_argument("--resume", action="store_true", help="Resume from existing JSONL output when possible.")
    parser.add_argument("--isolated", action="store_true", help="Run each case in a fresh subprocess.")
    parser.add_argument("--compare-baselines", action="store_true", help="Also run search_general and raw SearXNG for each case.")
    parser.add_argument("--somi-timeout", type=float, default=SOMI_TIMEOUT_S, help="Timeout in seconds for Somi evaluation inside each case.")
    parser.add_argument("--general-timeout", type=float, default=GENERAL_TIMEOUT_S, help="Timeout in seconds for search_general when baseline comparison is enabled.")
    parser.add_argument("--searx-timeout", type=float, default=SEARX_TIMEOUT_S, help="Timeout in seconds for raw SearXNG when baseline comparison is enabled.")
    parser.add_argument("--per-case-timeout", type=float, default=90.0, help="Timeout in seconds for isolated child runs.")
    parser.add_argument("--child-retries", type=int, default=1, help="Retry isolated child cases this many times after transient failure.")
    parser.add_argument("--no-inprocess-fallback", action="store_true", help="Do not retry timed-out child cases in-process; record a failure instead.")
    parser.add_argument("--save-every", type=int, default=5, help="Persist markdown every N cases.")
    parser.add_argument("--no-stdout-report", action="store_true", help="Do not print the full markdown report to stdout.")
    parser.add_argument("--stdout-summary-only", action="store_true", help="Print only the compact summary to stdout.")
    parser.add_argument("--hard-exit", action="store_true", help="Force process termination after writing outputs to avoid lingering worker threads during long benchmark runs.")
    parser.add_argument("--single-case-stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single_case_stdin:
        return _finalize_exit(asyncio.run(_single_case_from_stdin()), hard_exit=bool(args.hard_exit))
    if args.isolated:
        return _finalize_exit(_main_isolated(args), hard_exit=bool(args.hard_exit))
    return _finalize_exit(asyncio.run(_main_async(args)), hard_exit=bool(args.hard_exit))


if __name__ == "__main__":
    raise SystemExit(main())
