from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List

import workshop.tools.crawlies as crawlies

logger = logging.getLogger("testcrawlies_real")


DEFAULT_QUERIES = [
    "whats the latest hypertension guidelines",
    "bitcoin price history october 2021",
]


def _coerce_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _coerce_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _validate_run(
    query: str,
    out: Dict[str, Any],
    *,
    min_candidates: int,
    min_docs: int,
    min_quality: float,
    min_content_chars: int,
) -> List[str]:
    errors: List[str] = []

    candidates = out.get("candidates") or []
    docs = out.get("docs") or []

    if len(candidates) < int(min_candidates):
        errors.append(f"candidate_count {len(candidates)} < {min_candidates}")

    if len(docs) < int(min_docs):
        errors.append(f"doc_count {len(docs)} < {min_docs}")

    best_quality = 0.0
    best_len = 0
    for d in docs:
        try:
            qv = float(d.get("quality") or 0.0)
        except Exception:
            qv = 0.0
        best_quality = max(best_quality, qv)
        best_len = max(best_len, len(str(d.get("content") or "")))

    if best_quality < float(min_quality):
        errors.append(f"best_quality {best_quality:.2f} < {float(min_quality):.2f}")

    if best_len < int(min_content_chars):
        errors.append(f"best_content_len {best_len} < {min_content_chars}")

    if errors:
        logger.error("validation failed query='%s' errors=%s", query, errors)
    else:
        logger.info(
            "validation passed query='%s' candidates=%s docs=%s best_quality=%.2f best_len=%s",
            query,
            len(candidates),
            len(docs),
            best_quality,
            best_len,
        )

    return errors


async def _run_queries(args: argparse.Namespace) -> int:
    crawlies.configure_logging(args.log)

    queries = [q.strip() for q in (args.query or []) if q and str(q).strip()]
    if not queries:
        queries = list(DEFAULT_QUERIES)

    cfg = crawlies.CrawliesConfig(
        searx_base_url=str(args.searx),
        max_pages=_coerce_int(args.pages, 2),
        max_candidates=_coerce_int(args.candidates, 12),
        max_open_links=_coerce_int(args.open, 3),
        request_timeout_s=_coerce_float(args.request_timeout, 8.0),
        scrape_timeout_s=_coerce_float(args.scrape_timeout, 12.0),
        use_scrapling=not bool(args.no_scrapling),
        use_playwright=not bool(args.no_playwright),
        use_llm_rerank=bool(args.llm_rerank),
        llm_model=str(args.model),
        save_artifacts=not bool(args.no_artifacts),
        log_level=str(args.log),
    )

    engine = crawlies.CrawliesEngine(cfg)

    started = time.perf_counter()
    full_report: Dict[str, Any] = {
        "started_at": time.time(),
        "config": vars(args),
        "runs": [],
        "passed": True,
    }

    all_errors: List[str] = []

    logger.info("real test starting queries=%s", len(queries))
    for idx, query in enumerate(queries, 1):
        logger.info("run %s/%s query='%s'", idx, len(queries), query)
        out = await engine.crawl(query)

        errors = _validate_run(
            query,
            out,
            min_candidates=_coerce_int(args.min_candidates, 2),
            min_docs=_coerce_int(args.min_docs, 1),
            min_quality=_coerce_float(args.min_quality, 8.0),
            min_content_chars=_coerce_int(args.min_content_chars, 250),
        )

        full_report["runs"].append(
            {
                "query": query,
                "elapsed_ms": out.get("elapsed_ms"),
                "artifact_path": out.get("artifact_path"),
                "candidate_count": len(out.get("candidates") or []),
                "doc_count": len(out.get("docs") or []),
                "errors": errors,
                "raw": out,
            }
        )

        all_errors.extend([f"{query}: {e}" for e in errors])

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    full_report["elapsed_ms"] = round(elapsed_ms, 2)
    full_report["passed"] = len(all_errors) == 0
    full_report["errors"] = all_errors

    report_path = ""
    if args.report:
        report_path = str(args.report)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(full_report, f, ensure_ascii=False, indent=2)
        logger.info("report written: %s", report_path)

    print("\n=== REAL TEST SUMMARY ===")
    print(f"Queries: {len(queries)}")
    print(f"Elapsed: {round(elapsed_ms, 2)} ms")
    print(f"Passed: {full_report['passed']}")
    if report_path:
        print(f"Report: {report_path}")

    for run in full_report["runs"]:
        print(f"- {run['query']}")
        print(
            f"  candidates={run['candidate_count']} docs={run['doc_count']} "
            f"elapsed_ms={run.get('elapsed_ms')} errors={len(run.get('errors') or [])}"
        )

    if all_errors:
        print("\nFAILURES:")
        for e in all_errors:
            print(f"- {e}")
        return 1

    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Real integration test for crawlies retrieval (no smoke)")

    p.add_argument("--query", action="append", help="Query to test (repeatable). If omitted, uses default query set.")
    p.add_argument("--searx", default=os.getenv("CRAWLIES_SEARX", "http://localhost:8080"), help="SearXNG base URL")

    p.add_argument("--pages", type=int, default=2, help="SearX pages per query variant")
    p.add_argument("--candidates", type=int, default=12, help="Max candidate URLs")
    p.add_argument("--open", type=int, default=3, help="Top links to open")

    p.add_argument("--request-timeout", type=float, default=8.0, help="SearX request timeout seconds")
    p.add_argument("--scrape-timeout", type=float, default=12.0, help="Per-page scrape timeout seconds")

    p.add_argument("--min-candidates", type=int, default=2, help="Fail if candidates below this")
    p.add_argument("--min-docs", type=int, default=1, help="Fail if docs below this")
    p.add_argument("--min-quality", type=float, default=8.0, help="Fail if best doc quality below this")
    p.add_argument("--min-content-chars", type=int, default=250, help="Fail if best content length below this")

    p.add_argument("--no-scrapling", action="store_true", help="Disable Scrapling fetch path")
    p.add_argument("--no-playwright", action="store_true", help="Disable Playwright fetch path")
    p.add_argument("--llm-rerank", action="store_true", help="Enable LLM rerank")
    p.add_argument("--model", default=os.getenv("CRAWLIES_MODEL", "qwen3.5:0.8b"), help="LLM model for rerank")
    p.add_argument("--no-artifacts", action="store_true", help="Disable writing crawl artifacts")

    p.add_argument("--log", default="DEBUG", help="Log level")
    p.add_argument("--report", default="crawlies_real_report.json", help="Output report JSON path")
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run_queries(args))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
