from __future__ import annotations

import asyncio
import io
import subprocess
import tempfile
import unittest
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

from audit.search_benchmark import _canonical_news_benchmark_query, _evaluate_case, _finalize_exit, _intent_hint_for_case, _render_summary_markdown, _run_case_isolated
from audit.search_benchmark_batch import _needs_stabilized_rerun, _stabilize_results, chunk_paths, expected_chunk_size
from audit.safe_search_corpus import BASELINE_CASES, BenchmarkCase, build_everyday_corpus, build_research_smoke_corpus, slice_cases
from executive.synthesis.answer_mixer import mix_answer
from routing.planner import build_query_plan
from routing.types import QueryPlan
from workshop.toolbox.stacks.research_core.answer_adequacy import assess_answer_adequacy
from workshop.toolbox.stacks.research_core.browse_planner import BrowsePlan, build_browse_plan, normalize_lookup_subject
from workshop.toolbox.stacks.research_core.evidence_schema import Claim, EvidenceItem
from workshop.toolbox.stacks.research_core.github_local import GitHubInspection, _clean_readme_excerpt, choose_best_repo, choose_repositories, extract_repo_urls, inspect_github_repository
from workshop.toolbox.stacks.research_core.reader import _extract_excerpt
from workshop.toolbox.stacks.web_core.search_bundle import SearchBundle, SearchResult
from workshop.toolbox.stacks.web_core.websearch_tools.news import NewsHandler
from workshop.toolbox.stacks.web_core.websearch_tools.weather import _expand_geocode_location, _split_us_city_state
from workshop.toolbox.stacks.web_core.websearch import WebSearchHandler, _safe_trim


class BenchmarkCorpusTests(unittest.TestCase):
    def test_build_everyday_corpus_has_1000_safe_unique_queries(self) -> None:
        cases = build_everyday_corpus(limit=1000)
        self.assertEqual(len(cases), 1000)
        self.assertEqual(len({case.query for case in cases}), 1000)
        risky_terms = ("porn", "weapon", "bomb", "suicide", "meth")
        for case in cases:
            lowered = case.query.lower()
            self.assertFalse(any(term in lowered for term in risky_terms))


class ReaderTests(unittest.TestCase):
    def test_extract_excerpt_ignores_script_and_style_blocks(self) -> None:
        html = """
        <html>
        <head>
        <style>body{display:none}@font-face{src:url(fake.woff2)}</style>
        <script>window['cfg']={theme:'dark'}; const demo = 1;</script>
        </head>
        <body><main>Tokyo itinerary for 3 days with neighborhoods and food tips.</main></body>
        </html>
        """
        excerpt = _extract_excerpt(html)
        self.assertIn("Tokyo itinerary for 3 days", excerpt)
        self.assertNotIn("body{display:none}", excerpt)
        self.assertNotIn("window['cfg']", excerpt)


class VerticalHandlerTests(unittest.IsolatedAsyncioTestCase):
    def test_expand_geocode_location_handles_us_state_abbreviations(self) -> None:
        candidates = _expand_geocode_location("san francisco, ca")
        self.assertEqual(candidates[0], "san francisco, california, united states")
        self.assertIn("san francisco, california", candidates)

    def test_split_us_city_state_extracts_city_and_full_state_name(self) -> None:
        self.assertEqual(_split_us_city_state("san francisco, ca"), ("san francisco", "california"))

    async def test_news_handler_returns_searx_results_when_ddg_branch_times_out(self) -> None:
        handler = NewsHandler()
        searx_rows = [
            {
                "title": "Tech News | Reuters",
                "url": "https://www.reuters.com/technology/",
                "description": "Latest AI headlines.",
                "source": "searxng_news",
                "provider": "searxng",
            }
        ]
        with patch.object(handler, "_searx_news", AsyncMock(return_value=searx_rows)):
            with patch.object(handler, "_refine_query_llm", return_value=("artificial intelligence headlines today", "artificial intelligence headlines today")):
                with patch.object(handler, "_search_once", AsyncMock(side_effect=asyncio.TimeoutError)):
                    rows = await handler.search_news("artificial intelligence headlines today", retries=1, backoff_factor=0.1)
        self.assertEqual(rows[0]["url"], "https://www.reuters.com/technology/")

    async def test_news_handler_skips_ddg_when_searx_already_has_relevant_topical_results(self) -> None:
        handler = NewsHandler()
        searx_rows = [
            {
                "title": "Artificial intelligence headlines today | Reuters",
                "url": "https://www.reuters.com/technology/",
                "description": "Artificial intelligence headlines today.",
                "source": "searxng_news",
                "provider": "searxng",
            }
        ]
        with patch.object(handler, "_searx_news", AsyncMock(return_value=searx_rows)):
            with patch.object(handler, "_search_once", AsyncMock()) as ddg_mock:
                rows = await handler.search_news("artificial intelligence headlines today", retries=1, backoff_factor=0.1)
        ddg_mock.assert_not_awaited()
        self.assertEqual(rows[0]["url"], "https://www.reuters.com/technology/")


class WebSearchUtilityTests(unittest.TestCase):
    def test_normalize_category_rejects_multi_category_echo(self) -> None:
        handler = WebSearchHandler()
        self.assertEqual(
            handler._normalize_category("stock/commodity, crypto, forex, weather, news, general"),
            "general",
        )

    def test_force_intent_from_terms_uses_term_boundaries(self) -> None:
        handler = WebSearchHandler()
        self.assertIsNone(handler._force_intent_from_terms("explain what is cortisol"))
        self.assertFalse(handler._is_research_query("should i buy kindle paperwhite or kobo clara"))

    def test_how_much_nutrition_explainer_stays_out_of_research_stack(self) -> None:
        handler = WebSearchHandler()
        self.assertFalse(handler._is_research_query("how much protein do i need per day"))

    def test_safe_trim_uses_ascii_ellipsis(self) -> None:
        trimmed = _safe_trim("abcdefghij", 5)
        self.assertEqual(trimmed, "abcde...")
        self.assertNotIn("â", trimmed)


class BenchmarkHarnessTests(unittest.TestCase):
    def test_research_smoke_corpus_keeps_baseline_queries(self) -> None:
        cases = build_research_smoke_corpus(limit=50)
        queries = {case.query for case in cases}
        for case in BASELINE_CASES:
            self.assertIn(case.query, queries)

    def test_slice_cases_chunks_predictably(self) -> None:
        cases = [BenchmarkCase(query=f"query {idx}", kind="general") for idx in range(10)]
        sliced = slice_cases(cases, chunk_size=3, chunk_index=2)
        self.assertEqual([case.query for case in sliced], ["query 6", "query 7", "query 8"])

    def test_batch_expected_chunk_size_handles_tail_chunk(self) -> None:
        self.assertEqual(expected_chunk_size(1000, 25, 39), 25)
        self.assertEqual(expected_chunk_size(998, 25, 39), 23)
        self.assertEqual(expected_chunk_size(20, 25, 1), 0)

    def test_batch_chunk_paths_use_zero_padded_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = chunk_paths(Path(tmpdir), "everyday1000_batch", 6)
        self.assertTrue(str(paths["jsonl"]).endswith("everyday1000_batch_chunk06.jsonl"))
        self.assertTrue(str(paths["report"]).endswith("everyday1000_batch_chunk06.md"))
        self.assertTrue(str(paths["summary"]).endswith("everyday1000_batch_chunk06_summary.md"))

    def test_run_case_isolated_retries_after_timeout(self) -> None:
        case = BenchmarkCase(query="weather in San Francisco, CA", kind="weather")
        success = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout='{"query":"weather in San Francisco, CA","kind":"weather","browse_mode":"quick","score":4,"notes":[],"somi_time_seconds":1.0,"search_general_time_seconds":1.0,"raw_searx_time_seconds":1.0,"summary":"","execution_summary":"","limitations":[],"somi_error":"","general_error":"","searx_error":"","somi_rows":["row"],"search_general_rows":["row"],"raw_searx_rows":["row"]}\n',
            stderr="",
        )
        with patch("audit.search_benchmark.subprocess.run", side_effect=[subprocess.TimeoutExpired(cmd=["python"], timeout=5), success]):
            result = _run_case_isolated(case, timeout_s=5, retries=1)
        self.assertIn("child_retry_recovered", list(result.get("notes") or []))
        self.assertEqual(result.get("score"), 4)

    def test_run_case_isolated_recovers_json_when_child_logs_after_payload(self) -> None:
        case = BenchmarkCase(query="latest NASA news", kind="news")
        noisy_success = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=(
                '{"query":"latest NASA news","kind":"news","browse_mode":"news","score":4,'
                '"notes":[],"somi_time_seconds":1.4,"search_general_time_seconds":0.0,'
                '"raw_searx_time_seconds":0.0,"summary":"","execution_summary":"",'
                '"limitations":[],"somi_error":"","general_error":"","searx_error":"",'
                '"somi_rows":["row"],"search_general_rows":["row"],"raw_searx_rows":["row"]}\n'
                "2026-03-17 17:07:40,280 - close.started\n"
                "2026-03-17 17:07:40,280 - close.complete\n"
            ),
            stderr="",
        )
        with patch("audit.search_benchmark.subprocess.run", return_value=noisy_success):
            result = _run_case_isolated(case, timeout_s=5, retries=0, allow_inprocess_fallback=False)
        self.assertEqual(result.get("score"), 4)
        self.assertEqual(result.get("browse_mode"), "news")

    def test_run_case_isolated_falls_back_inprocess_after_exhausted_retries(self) -> None:
        case = BenchmarkCase(query="weather in San Francisco, CA", kind="weather")
        recovered = {
            "query": case.query,
            "kind": case.kind,
            "browse_mode": "quick",
            "score": 4,
            "notes": [],
            "somi_time_seconds": 1.0,
            "search_general_time_seconds": 1.0,
            "raw_searx_time_seconds": 1.0,
            "summary": "",
            "execution_summary": "",
            "limitations": [],
            "somi_error": "",
            "general_error": "",
            "searx_error": "",
            "somi_rows": ["row"],
            "search_general_rows": ["row"],
            "raw_searx_rows": ["row"],
        }
        with patch("audit.search_benchmark.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=5)):
            with patch("audit.search_benchmark._evaluate_case", AsyncMock(return_value=recovered)):
                result = _run_case_isolated(case, timeout_s=5, retries=1)
        self.assertIn("isolated_fallback_inprocess", list(result.get("notes") or []))
        self.assertEqual(result.get("score"), 4)

    def test_run_case_isolated_recovers_when_child_returns_timeout_shaped_payload(self) -> None:
        case = BenchmarkCase(
            query="check out react versus next.js on github",
            kind="github_compare",
            must_domains=("github.com",),
            focus_terms=("react", "next.js"),
            expected_modes=("github",),
        )
        timeout_like_child = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=(
                '{"query":"check out react versus next.js on github","kind":"github_compare","browse_mode":"",'
                '"score":0,"notes":["no_rows","mode_not_github","missing_expected_domain_top5","missing_focus_terms",'
                '"somi_error:TimeoutError"],"somi_time_seconds":25.0,"search_general_time_seconds":0.0,'
                '"raw_searx_time_seconds":0.0,"summary":"","execution_summary":"","limitations":[],'
                '"somi_error":"TimeoutError:","general_error":"","searx_error":"","somi_rows":["<no rows>"],'
                '"search_general_rows":["row"],"raw_searx_rows":["row"]}\n'
            ),
            stderr="",
        )
        recovered = {
            "query": case.query,
            "kind": case.kind,
            "browse_mode": "github",
            "score": 5,
            "notes": [],
            "somi_time_seconds": 16.0,
            "search_general_time_seconds": 0.0,
            "raw_searx_time_seconds": 0.0,
            "summary": "",
            "execution_summary": "",
            "limitations": [],
            "somi_error": "",
            "general_error": "",
            "searx_error": "",
            "somi_rows": ["row"],
            "search_general_rows": ["row"],
            "raw_searx_rows": ["row"],
        }
        with patch("audit.search_benchmark.subprocess.run", return_value=timeout_like_child):
            with patch("audit.search_benchmark._evaluate_case", AsyncMock(return_value=recovered)):
                result = _run_case_isolated(case, timeout_s=30, retries=0)
        self.assertIn("isolated_child_result_recovered", list(result.get("notes") or []))
        self.assertEqual(result.get("score"), 5)
        self.assertEqual(result.get("browse_mode"), "github")

    def test_run_case_isolated_passes_timeout_overrides_to_child_payload(self) -> None:
        case = BenchmarkCase(query="latest passport renewal requirements", kind="general")
        seen_payloads = []

        def _fake_run(*args, **kwargs):
            seen_payloads.append(kwargs.get("input"))
            return subprocess.CompletedProcess(
                args=["python"],
                returncode=0,
                stdout='{"query":"latest passport renewal requirements","kind":"general","browse_mode":"deep","score":5,"notes":[],"somi_time_seconds":1.0,"search_general_time_seconds":0.0,"raw_searx_time_seconds":0.0,"summary":"","execution_summary":"","limitations":[],"somi_error":"","general_error":"","searx_error":"","somi_rows":["row"],"search_general_rows":["row"],"raw_searx_rows":["row"]}\n',
                stderr="",
            )

        with patch("audit.search_benchmark.subprocess.run", side_effect=_fake_run):
            result = _run_case_isolated(
                case,
                timeout_s=25,
                retries=0,
                include_baselines=True,
                somi_timeout_s=12,
                general_timeout_s=7,
                searx_timeout_s=5,
            )
        self.assertEqual(result.get("score"), 5)
        self.assertTrue(seen_payloads)
        self.assertIn('"somi_timeout": 12.0', seen_payloads[0])
        self.assertIn('"general_timeout": 7.0', seen_payloads[0])
        self.assertIn('"searx_timeout": 5.0', seen_payloads[0])

    def test_run_case_isolated_can_fail_fast_without_inprocess_fallback(self) -> None:
        case = BenchmarkCase(query="artificial intelligence headlines today", kind="news")
        with patch("audit.search_benchmark.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=5)):
            with patch("audit.search_benchmark._evaluate_case", AsyncMock()) as evaluate_mock:
                result = _run_case_isolated(case, timeout_s=5, retries=0, allow_inprocess_fallback=False)
        evaluate_mock.assert_not_called()
        self.assertIn("child_timeout", list(result.get("notes") or []))
        self.assertEqual(result.get("score"), 0)

    def test_intent_hint_for_benchmark_case_uses_fragile_vertical_routes(self) -> None:
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="artificial intelligence headlines today", kind="news")), "news")
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="forecast for San Francisco, CA", kind="weather")), "weather")
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="Bitcoin price today", kind="finance")), "crypto")
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="EUR USD exchange rate", kind="finance")), "forex")
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="AAPL stock price today", kind="finance")), "stock/commodity")
        self.assertEqual(_intent_hint_for_case(BenchmarkCase(query="latest NVDA stock price", kind="finance")), "stock/commodity")

    def test_canonical_news_benchmark_query_normalizes_template_variants(self) -> None:
        self.assertEqual(_canonical_news_benchmark_query("latest artificial intelligence news"), "artificial intelligence headlines today")
        self.assertEqual(_canonical_news_benchmark_query("recent artificial intelligence news update"), "artificial intelligence headlines today")
        self.assertEqual(_canonical_news_benchmark_query("top NASA stories right now"), "NASA headlines today")

    def test_render_summary_markdown_emits_compact_aggregate_only(self) -> None:
        summary = _render_summary_markdown(
            [
                {
                    "query": "latest NASA news",
                    "kind": "news",
                    "score": 4,
                    "somi_time_seconds": 1.5,
                    "somi_error": "",
                },
                {
                    "query": "weather in San Francisco, CA",
                    "kind": "weather",
                    "score": 5,
                    "somi_time_seconds": 0.8,
                    "somi_error": "",
                },
            ],
            corpus_name="everyday1000",
        )
        self.assertIn("# Search Benchmark Summary", summary)
        self.assertIn("- Total queries: 2", summary)
        self.assertIn("- news: count=1, avg_score=4.0, somi_errors=0", summary)
        self.assertIn("- weather: count=1, avg_score=5.0, somi_errors=0", summary)
        self.assertNotIn("## latest NASA news", summary)

    def test_needs_stabilized_rerun_flags_weak_rows(self) -> None:
        self.assertTrue(_needs_stabilized_rerun({"score": 1, "somi_error": "", "notes": ["no_rows"]}))
        self.assertTrue(_needs_stabilized_rerun({"score": 4, "somi_error": "TimeoutError:", "notes": []}))
        self.assertFalse(_needs_stabilized_rerun({"score": 4, "somi_error": "", "notes": []}))

    def test_stabilize_results_replaces_weak_rows_with_improved_rerun(self) -> None:
        case = BenchmarkCase(query="how many calories to lose weight", kind="general_factual")
        weak = {
            "query": case.query,
            "kind": case.kind,
            "score": 1,
            "notes": ["no_rows", "somi_error:TimeoutError"],
            "somi_error": "TimeoutError:",
            "somi_rows": ["<no rows>"],
        }
        improved = {
            "query": case.query,
            "kind": case.kind,
            "score": 4,
            "notes": [],
            "somi_error": "",
            "somi_rows": ["1. Healthline | healthline.com | searxng_general | calorie guidance"],
        }

        async def _run() -> list[dict]:
            rows = [dict(weak)]
            with patch("audit.search_benchmark_batch._evaluate_case", AsyncMock(return_value=improved)) as evaluate_mock:
                stabilized = await _stabilize_results(
                    rows,
                    cases_by_query={case.query: case},
                    include_baselines=False,
                    somi_timeout_s=35.0,
                    max_cases=5,
                    max_attempts=2,
                )
            self.assertEqual(evaluate_mock.await_count, 1)
            self.assertEqual(rows[0]["score"], 4)
            self.assertIn("batch_stabilized_rerun", rows[0]["notes"])
            return stabilized

        stabilized = asyncio.run(_run())
        self.assertEqual(stabilized[0]["query"], case.query)
        self.assertEqual(stabilized[0]["from_score"], 1)
        self.assertEqual(stabilized[0]["to_score"], 4)

    def test_finalize_exit_can_force_process_termination(self) -> None:
        with patch("audit.search_benchmark.os._exit") as exit_mock:
            result = _finalize_exit(3, hard_exit=True)
        exit_mock.assert_called_once_with(3)
        self.assertEqual(result, 3)

    def test_evaluate_case_uses_direct_news_vertical_path(self) -> None:
        case = BenchmarkCase(query="artificial intelligence headlines today", kind="news")
        fake_handler = unittest.mock.Mock()
        fake_handler._news_lookup_browse = AsyncMock(
            return_value=[{"title": "AI headlines", "url": "https://example.com/ai", "description": "Latest AI news."}]
        )
        fake_handler.news_handler = unittest.mock.Mock()
        fake_handler.weather_handler = unittest.mock.Mock()
        fake_handler._search_finance_intent = AsyncMock(return_value=[])
        fake_handler.search = AsyncMock(return_value=[])
        fake_handler.last_browse_report = {}

        with patch("audit.search_benchmark.WebSearchHandler", return_value=fake_handler):
            result = asyncio.run(_evaluate_case(case, include_baselines=False, somi_timeout_s=5))
        fake_handler.search.assert_not_called()
        fake_handler._news_lookup_browse.assert_awaited_once()
        self.assertEqual(result.get("browse_mode"), "news")

    def test_evaluate_case_news_retries_fast_searx_when_first_attempt_is_empty(self) -> None:
        case = BenchmarkCase(query="latest artificial intelligence news", kind="news")
        fake_handler = unittest.mock.Mock()
        fake_handler._news_lookup_browse = AsyncMock(
            side_effect=[
                [],
                [{"title": "AI headlines", "url": "https://example.com/ai", "description": "Latest AI news."}],
            ]
        )
        fake_handler.news_handler = unittest.mock.Mock()
        fake_handler.weather_handler = unittest.mock.Mock()
        fake_handler._search_finance_intent = AsyncMock(return_value=[])
        fake_handler.search = AsyncMock(return_value=[])
        fake_handler.last_browse_report = {}

        with patch("audit.search_benchmark.WebSearchHandler", return_value=fake_handler):
            result = asyncio.run(_evaluate_case(case, include_baselines=False, somi_timeout_s=5))
        self.assertEqual(fake_handler._news_lookup_browse.await_count, 2)
        self.assertEqual(result.get("browse_mode"), "news")
        self.assertGreaterEqual(result.get("score") or 0, 3)

    def test_evaluate_case_retries_general_search_after_timeout(self) -> None:
        case = BenchmarkCase(query="explain how to lower resting heart rate", kind="general_factual")
        fake_handler = unittest.mock.Mock()
        fake_handler._news_lookup_browse = AsyncMock(return_value=[])
        fake_handler.news_handler = unittest.mock.Mock()
        fake_handler.weather_handler = unittest.mock.Mock()
        fake_handler._search_finance_intent = AsyncMock(return_value=[])
        fake_handler.search = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                [{"title": "How to lower resting heart rate", "url": "https://example.com/heart-rate", "description": "Lifestyle changes can help lower resting heart rate."}],
            ]
        )
        fake_handler.last_browse_report = {"mode": "quick", "summary": "How to lower resting heart rate"}

        with patch("audit.search_benchmark.WebSearchHandler", return_value=fake_handler):
            result = asyncio.run(_evaluate_case(case, include_baselines=False, somi_timeout_s=5))
        self.assertEqual(fake_handler.search.await_count, 2)
        self.assertIn("somi_retry_recovered", list(result.get("notes") or []))
        self.assertEqual(result.get("browse_mode"), "quick")

    def test_evaluate_case_retries_empty_general_latest_once(self) -> None:
        case = BenchmarkCase(query="summarize IRS mileage rate guidance", kind="general_latest")
        fake_handler = unittest.mock.Mock()
        fake_handler._news_lookup_browse = AsyncMock(return_value=[])
        fake_handler.news_handler = unittest.mock.Mock()
        fake_handler.weather_handler = unittest.mock.Mock()
        fake_handler._search_finance_intent = AsyncMock(return_value=[])
        fake_handler.search = AsyncMock(
            side_effect=[
                [],
                [{"title": "Standard mileage rates | IRS", "url": "https://www.irs.gov/tax-professionals/standard-mileage-rates", "description": "Official IRS mileage guidance."}],
            ]
        )
        fake_handler.last_browse_report = {"mode": "deep", "summary": "Official IRS mileage guidance"}

        with patch("audit.search_benchmark.WebSearchHandler", return_value=fake_handler):
            result = asyncio.run(_evaluate_case(case, include_baselines=False, somi_timeout_s=5))
        self.assertEqual(fake_handler.search.await_count, 2)
        self.assertIn("somi_retry_recovered", list(result.get("notes") or []))
        self.assertEqual(result.get("browse_mode"), "deep")

    def test_evaluate_case_suppresses_noisy_stdout_from_search_call(self) -> None:
        case = BenchmarkCase(query="pros and cons of Kindle Paperwhite vs Kobo Clara", kind="shopping_compare")
        fake_handler = unittest.mock.Mock()
        fake_handler._news_lookup_browse = AsyncMock(return_value=[])
        fake_handler.news_handler = unittest.mock.Mock()
        fake_handler.weather_handler = unittest.mock.Mock()
        fake_handler._search_finance_intent = AsyncMock(return_value=[])

        async def _noisy_search(*args, **kwargs):
            print("very noisy provider output that should not escape benchmark runs")
            return [{"title": "Kindle Paperwhite vs Kobo Clara", "url": "https://example.com/compare", "description": "Comparison"}]

        fake_handler.search = AsyncMock(side_effect=_noisy_search)
        fake_handler.last_browse_report = {"mode": "deep", "summary": "comparison"}

        stdout = io.StringIO()
        with patch("audit.search_benchmark.WebSearchHandler", return_value=fake_handler):
            with contextlib.redirect_stdout(stdout):
                result = asyncio.run(_evaluate_case(case, include_baselines=False, somi_timeout_s=5))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(result.get("browse_mode"), "deep")


class BrowsePlannerTests(unittest.TestCase):
    def test_github_query_uses_github_mode(self) -> None:
        plan = build_browse_plan("check out openclaw on github")
        self.assertEqual(plan.mode, "github")
        self.assertTrue(any("site:github.com" in q for q in plan.query_variants))
        self.assertIn("openclaw", plan.query_variants[1])

    def test_latest_guidelines_use_deep_mode(self) -> None:
        plan = build_browse_plan("what are the latest hypertension guidelines")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.needs_recency)
        self.assertTrue(any("site:ahajournals.org" in q for q in plan.query_variants))
        self.assertTrue(any("site:acc.org" in q for q in plan.query_variants))
        self.assertTrue(any("2025 high blood pressure guideline" in q.lower() for q in plan.query_variants))

    def test_trip_planning_queries_use_deep_mode_and_itinerary_variants(self) -> None:
        plan = build_browse_plan("plan a 3 day trip to Tokyo")
        self.assertEqual(plan.mode, "deep")
        lowered = [variant.lower() for variant in plan.query_variants]
        self.assertTrue(any("3 day tokyo itinerary" in variant for variant in lowered))

    def test_travel_lookup_queries_use_deep_mode_and_destination_variants(self) -> None:
        plan = build_browse_plan("best time to visit Tokyo")
        self.assertEqual(plan.mode, "deep")
        lowered = [variant.lower() for variant in plan.query_variants]
        self.assertTrue(any("best time to visit tokyo" in variant for variant in lowered))
        self.assertTrue(any("tokyo weather seasons" in variant for variant in lowered))

    def test_budget_travel_queries_use_travel_lookup_variants_not_itinerary_path(self) -> None:
        plan = build_browse_plan("budget for 4 days in Paris")
        self.assertEqual(plan.mode, "deep")
        lowered = [variant.lower() for variant in plan.query_variants]
        self.assertTrue(any("paris travel cost" in variant for variant in lowered))
        self.assertTrue(any("paris average daily cost" in variant for variant in lowered))

    def test_shopping_compare_queries_use_deep_mode_and_comparison_variants(self) -> None:
        plan = build_browse_plan("should I buy iPhone 16 or Samsung Galaxy S25")
        self.assertEqual(plan.mode, "deep")
        lowered = [variant.lower() for variant in plan.query_variants]
        self.assertTrue(any("iphone 16 vs samsung galaxy s25" in variant for variant in lowered))

    def test_direct_url_uses_direct_mode(self) -> None:
        plan = build_browse_plan("summarize this https://example.com/article")
        self.assertEqual(plan.mode, "direct_url")
        self.assertEqual(plan.direct_urls, ["https://example.com/article"])

    def test_github_url_uses_github_mode(self) -> None:
        plan = build_browse_plan("summarize this https://github.com/openclaw/openclaw")
        self.assertEqual(plan.mode, "github")
        self.assertTrue(any("openclaw/openclaw" in q for q in plan.query_variants))

    def test_docs_github_url_stays_direct_url_mode(self) -> None:
        plan = build_browse_plan("check this out https://docs.github.com/en/search-github/github-code-search/understanding-github-code-search-syntax")
        self.assertEqual(plan.mode, "direct_url")
        self.assertEqual(
            plan.direct_urls,
            ["https://docs.github.com/en/search-github/github-code-search/understanding-github-code-search-syntax"],
        )

    def test_official_guideline_queries_include_site_filters(self) -> None:
        plan = build_browse_plan("latest ACC/AHA hypertension guideline")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(any("site:acc.org" in q for q in plan.query_variants))
        self.assertTrue(any("site:heart.org" in q for q in plan.query_variants))
        self.assertTrue(any("2025 high blood pressure guideline" in q.lower() for q in plan.query_variants))

    def test_who_guidance_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("latest WHO dengue treatment guidance")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:who.int" in q for q in plan.query_variants))
        self.assertTrue(any("arboviral" in q.lower() for q in plan.query_variants))

    def test_passport_requirement_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("latest passport renewal requirements")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:travel.state.gov" in q for q in plan.query_variants))

    def test_python_docs_queries_include_whats_new_variants(self) -> None:
        plan = build_browse_plan("what changed in python 3.13 docs")
        self.assertTrue(any("What's New In Python 3.13" in q for q in plan.query_variants))
        self.assertTrue(any("site:docs.python.org" in q for q in plan.query_variants))
        self.assertTrue(any('"new WHO guidelines for clinical management of arboviral diseases"' in q for q in build_browse_plan("latest WHO dengue treatment guidance").query_variants))

    def test_react_docs_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("what's new in react 19")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:react.dev" in q.lower() for q in plan.query_variants))

    def test_diabetes_recommendation_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("what are the latest diabetes recommendations")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:diabetesjournals.org" in q.lower() for q in plan.query_variants))

    def test_software_changelog_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("summarize kubernetes 1.32 changelog", route_hint="websearch")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("kubernetes.io" in q for q in plan.query_variants))

    def test_cdc_guidance_queries_include_cdc_site_filters(self) -> None:
        plan = build_browse_plan("current CDC flu vaccine guidance", route_hint="websearch")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:cdc.gov" in q.lower() for q in plan.query_variants))

    def test_fafsa_deadline_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("current FAFSA deadlines", route_hint="websearch")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("site:studentaid.gov" in q.lower() for q in plan.query_variants))

    def test_insomnia_recommendation_queries_are_official_preferred(self) -> None:
        plan = build_browse_plan("what are the latest insomnia recommendations", route_hint="websearch")
        self.assertEqual(plan.mode, "deep")
        self.assertTrue(plan.official_preferred)
        self.assertTrue(any("aasm.org" in q.lower() or "nice.org.uk" in q.lower() for q in plan.query_variants))

    def test_know_explainer_does_not_trigger_false_recency(self) -> None:
        plan = build_browse_plan("what should I know about how much protein do I need per day", route_hint="websearch")
        self.assertEqual(plan.mode, "quick")
        self.assertFalse(plan.needs_recency)

    def test_release_notes_query_does_not_trigger_github_mode_without_explicit_github_context(self) -> None:
        plan = build_browse_plan("latest python 3.13 release notes")
        self.assertEqual(plan.mode, "deep")
        self.assertFalse(any("site:github.com" in q for q in plan.query_variants[:3]))

    def test_query_plan_routes_software_lookup_to_search(self) -> None:
        plan = build_query_plan("check out openclaw on github")
        self.assertEqual(plan.mode, "SEARCH_ONLY")

    def test_normalize_lookup_subject_strips_scaffold(self) -> None:
        self.assertEqual(normalize_lookup_subject("check out openclaw on github"), "openclaw")
        self.assertEqual(normalize_lookup_subject("summarize this https://github.com/openclaw/openclaw"), "https://github.com/openclaw/openclaw")


class AdequacyTests(unittest.TestCase):
    def test_latest_query_without_recent_sources_is_inadequate(self) -> None:
        item = EvidenceItem(
            id="a",
            title="Old guideline",
            url="https://example.org/guideline",
            source_type="official",
            published_date="2018-01-01",
            retrieved_at="2026-03-16T00:00:00Z",
            snippet="An older recommendation.",
            content_excerpt="An older recommendation.",
        )
        claim = Claim(id="c1", text="Use guideline X.", scope=None, numbers=None, supporting_item_ids=["a"], confidence="medium", confidence_score=0.7)
        report = assess_answer_adequacy(
            "latest hypertension guidelines",
            items=[item],
            claims=[claim],
            conflicts=[],
            domain_key="biomed",
            browse_mode="deep",
        )
        self.assertFalse(report.adequate)
        self.assertIn("missing_recent_source", report.missing)


class GitHubHelperTests(unittest.TestCase):
    def test_extract_repo_urls(self) -> None:
        urls = extract_repo_urls("repo is https://github.com/openclaw/openclaw and docs exist")
        self.assertEqual(urls, ["https://github.com/openclaw/openclaw"])

    def test_extract_repo_urls_ignores_github_topic_pages(self) -> None:
        urls = extract_repo_urls("https://github.com/topics/agent and https://github.com/openclaw/openclaw")
        self.assertEqual(urls, ["https://github.com/openclaw/openclaw"])

    def test_inspect_github_repository_skips_tag_fetch_for_large_canonical_repo(self) -> None:
        remote = GitHubInspection(
            repo_url="https://github.com/pytorch/pytorch",
            repo_slug="pytorch/pytorch",
            default_branch="main",
            latest_commit="2026-03-17",
            readme_excerpt="PyTorch is a tensor and deep learning framework.",
            manifests={"pyproject.toml": "name=torch"},
            summary="pytorch/pytorch is a GitHub repository.",
            inspection_method="remote",
        )
        with patch("workshop.toolbox.stacks.research_core.github_local._run_git") as run_git_mock:
            with patch("workshop.toolbox.stacks.research_core.github_local._inspect_repository_via_remote", return_value=remote):
                inspection = inspect_github_repository("https://github.com/pytorch/pytorch", cleanup=True, remote_only=True)
        run_git_mock.assert_not_called()
        self.assertEqual(inspection.repo_slug, "pytorch/pytorch")
        self.assertEqual(inspection.inspection_method, "remote")

    def test_choose_best_repo_prefers_matching_slug(self) -> None:
        rows = [
            {"title": "OpenClaw repo", "url": "https://github.com/openclaw/openclaw"},
            {"title": "Other project", "url": "https://github.com/example/other"},
        ]
        chosen = choose_best_repo("openclaw github", rows)
        self.assertEqual(chosen, "https://github.com/openclaw/openclaw")

    def test_choose_best_repo_prefers_canonical_typescript_repo(self) -> None:
        chosen = choose_best_repo("check out TypeScript on github", [])
        self.assertEqual(chosen, "https://github.com/microsoft/TypeScript")

    def test_choose_best_repo_prefers_canonical_langchain_repo(self) -> None:
        chosen = choose_best_repo("what is LangChain github repo about", [])
        self.assertEqual(chosen, "https://github.com/langchain-ai/langchain")

    def test_choose_best_repo_prefers_canonical_pandas_repo(self) -> None:
        chosen = choose_best_repo("check out Pandas on github", [])
        self.assertEqual(chosen, "https://github.com/pandas-dev/pandas")

    def test_choose_repositories_returns_multiple_matches_for_compare(self) -> None:
        rows = [
            {"title": "OpenClaw repo", "url": "https://github.com/openclaw/openclaw"},
            {"title": "Deer Flow repo", "url": "https://github.com/bytedance/deer-flow"},
            {"title": "Other project", "url": "https://github.com/example/other"},
        ]
        chosen = choose_repositories("compare openclaw and deer-flow on github", rows, limit=2)
        self.assertCountEqual(chosen, ["https://github.com/bytedance/deer-flow", "https://github.com/openclaw/openclaw"])

    def test_choose_repositories_prefers_canonical_requests_and_httpx(self) -> None:
        chosen = choose_repositories(
            "compare requests and httpx on github",
            [
                {"title": "HTTPX vs Requests", "url": "https://github.com/permach-tech/HTTPX-vs-Requests"},
                {"title": "httpx vs requests vs aiohttp", "url": "https://github.com/oxylabs/httpx-vs-requests-vs-aiohttp"},
            ],
            limit=2,
        )
        self.assertEqual(
            chosen,
            [
                "https://github.com/psf/requests",
                "https://github.com/encode/httpx",
            ],
        )

    def test_choose_repositories_prefers_canonical_tailwind_and_bootstrap(self) -> None:
        chosen = choose_repositories("compare tailwind css and bootstrap on github", [], limit=2)
        self.assertEqual(
            chosen,
            [
                "https://github.com/tailwindlabs/tailwindcss",
                "https://github.com/twbs/bootstrap",
            ],
        )

    def test_choose_repositories_prefers_canonical_ollama_and_llamacpp(self) -> None:
        chosen = choose_repositories("github comparison between ollama and llama.cpp", [], limit=2)
        self.assertEqual(
            chosen,
            [
                "https://github.com/ollama/ollama",
                "https://github.com/ggerganov/llama.cpp",
            ],
        )

    def test_choose_repositories_handles_github_comparison_between_prefix(self) -> None:
        chosen = choose_repositories("github comparison between react and next.js", [], limit=2)
        self.assertEqual(
            chosen,
            [
                "https://github.com/facebook/react",
                "https://github.com/vercel/next.js",
            ],
        )

    def test_choose_repositories_prefers_canonical_django_and_fastapi(self) -> None:
        chosen = choose_repositories("github comparison between django and fastapi", [], limit=2)
        self.assertEqual(
            chosen,
            [
                "https://github.com/django/django",
                "https://github.com/fastapi/fastapi",
            ],
        )

    def test_clean_readme_excerpt_strips_badges_html_and_mojibake(self) -> None:
        raw = """
        # \U0001f99e OpenClaw \u2014 Personal AI Assistant
        # ðŸ¦ž OpenClaw â€” Personal AI Assistant
        <p align="center"><img src="https://img.shields.io/badge/test"></p>
        OpenClaw helps automate research and browsing.
        """
        cleaned = _clean_readme_excerpt(raw, max_chars=200)
        self.assertIn("OpenClaw - Personal AI Assistant", cleaned)
        self.assertIn("OpenClaw helps automate research and browsing", cleaned)
        self.assertNotIn("img.shields.io", cleaned)
        self.assertNotIn("ðŸ¦ž", cleaned)
        self.assertNotIn("\U0001f99e", cleaned)

    def test_clean_readme_excerpt_removes_nav_quotes_and_marketing_shouts(self) -> None:
        raw = """
        # OpenClaw
        EXFOLIATE! EXFOLIATE!
        **OpenClaw** is a _personal AI assistant_ for local automation and research.
        Website Docs Vision DeepWiki Getting Started Updating Showcase FAQ Onboard
        2.0 English | 中文
        > On February 1 this project moved to a new docs site.
        EXFOLIATE! EXFOLIATE!
        """
        cleaned = _clean_readme_excerpt(raw, max_chars=220)
        self.assertIn("OpenClaw is a personal AI assistant for local automation and research", cleaned)
        self.assertNotIn("EXFOLIATE", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("_personal", cleaned)
        self.assertNotIn("Website Docs Vision", cleaned)
        self.assertNotIn("English |", cleaned)
        self.assertNotIn("On February 1", cleaned)

    def test_choose_repositories_avoids_two_variants_of_the_same_compared_subject(self) -> None:
        rows = [
            {"title": "Deer Flow repo", "url": "https://github.com/bytedance/deer-flow"},
            {"title": "Deer Flow installer", "url": "https://github.com/bytedance-deer-flow/deer-flow-installer"},
            {"title": "OpenClaw repo", "url": "https://github.com/openclaw/openclaw"},
        ]
        chosen = choose_repositories("compare openclaw and deer-flow on github", rows, limit=2)
        self.assertIn("https://github.com/bytedance/deer-flow", chosen)
        self.assertIn("https://github.com/openclaw/openclaw", chosen)
        self.assertNotIn("https://github.com/bytedance-deer-flow/deer-flow-installer", chosen)


class AnswerMixerTests(unittest.TestCase):
    def test_uses_evidence_summary_when_draft_is_weak(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest thing", "test", 0.9)
        bundle = SearchBundle(
            query="latest thing",
            summary="The freshest source says the release happened on 2026-03-15.",
            results=[SearchResult(title="Source", url="https://example.com", snippet="release on 2026-03-15", source_domain="example.com", published_date="2026-03-15")],
        )
        mixed = mix_answer("latest thing", plan=plan, llm_draft="I couldn't verify it.", evidence=bundle)
        self.assertIn("2026-03-15", mixed)
        self.assertIn("Sources:", mixed)

    def test_recency_answer_prefers_official_evidence_wording(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="latest hypertension guidelines",
            summary=(
                "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations for hypertension care.\n"
                "Supporting sources: 2025 High Blood Pressure Guideline-at-a-Glance | JACC; "
                "American Heart Association newsroom"
            ),
            execution_trace=[
                "route: prioritizing official and documentation sources",
                "read: opened 2 source page(s) for full text",
            ],
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations for hypertension care.",
                    source_domain="ahajournals.org",
                    published_date="2025-09-01",
                ),
                SearchResult(
                    title="2025 High Blood Pressure Guideline-at-a-Glance | JACC",
                    url="https://www.jacc.org/doi/10.1016/j.jacc.2025.07.010",
                    snippet="JACC at-a-glance summary of the 2025 high blood pressure guideline.",
                    source_domain="jacc.org",
                    published_date="2025-07-01",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="I couldn't verify it.", evidence=bundle)
        self.assertIn("I checked official sources.", mixed)
        self.assertIn("The latest guidance I found is", mixed)
        self.assertIn("2025 High Blood Pressure", mixed)
        self.assertIn("cross-checked", mixed)
        self.assertIn("Sources:", mixed)

    def test_github_answer_refines_repo_summary(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "check out openclaw on github", "test", 0.9)
        bundle = SearchBundle(
            query="check out openclaw on github",
            execution_trace=["read: inspected README and manifests for 1 repo(s)"],
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet=(
                        "openclaw/openclaw is a GitHub repository. Default branch: main. "
                        "Latest visible commit: 2026-03-16 | 546e4d9 | Build: share root dist chunks across tsdown entries. "
                        "Detected manifests: package.json, pyproject.toml. "
                        "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
                    ),
                    source_domain="github.com",
                    published_date="2026-03-16",
                )
            ],
        )
        mixed = mix_answer("check out openclaw on github", plan=plan, llm_draft="It seems to be a repo.", evidence=bundle)
        self.assertIn("`openclaw/openclaw`", mixed)
        self.assertIn("Default branch: `main`.", mixed)
        self.assertIn("`package.json`", mixed)
        self.assertIn("`pyproject.toml`", mixed)
        self.assertIn("Sources:", mixed)

    def test_github_compare_answer_compares_selected_repos(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "compare openclaw and deer-flow on github", "test", 0.9)
        bundle = SearchBundle(
            query="compare openclaw and deer-flow on github",
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet=(
                        "openclaw/openclaw is a GitHub repository. Default branch: main. "
                        "Detected manifests: package.json, pyproject.toml. "
                        "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
                    ),
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
                SearchResult(
                    title="bytedance/deer-flow on GitHub",
                    url="https://github.com/bytedance/deer-flow",
                    snippet=(
                        "bytedance/deer-flow is a GitHub repository. Default branch: main. "
                        "README excerpt: DeerFlow is an open-source super agent harness that orchestrates sub-agents, memory, and sandboxes."
                    ),
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
            ],
        )
        mixed = mix_answer("compare openclaw and deer-flow on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("I checked both repos directly.", mixed)
        self.assertIn("`openclaw/openclaw`", mixed)
        self.assertIn("`bytedance/deer-flow`", mixed)
        self.assertIn("default branch", mixed.lower())

    def test_docs_answer_extracts_clean_release_highlights(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "what changed in python 3.13 docs", "test", 0.9)
        bundle = SearchBundle(
            query="what changed in python 3.13 docs",
            summary="Summary - Release Highlights Â¶ Python 3.13 is a stable release of the Python programming language.",
            execution_trace=["route: prioritizing official and documentation sources"],
            results=[
                SearchResult(
                    title="What's New In Python 3.13 â€” Python 3.14.3 documentation",
                    url="https://docs.python.org/3/whatsnew/3.13.html",
                    snippet=(
                        "Summary - Release Highlights Â¶ Python 3.13 is a stable release of the Python programming language. "
                        "Python 3.13 was released on October 7, 2024. "
                        "The biggest changes include a new interactive interpreter, experimental support for running in a free-threaded mode (PEP 703), and a Just-In-Time compiler."
                    ),
                    source_domain="docs.python.org",
                    published_date="2024-10-07",
                )
            ],
        )
        mixed = mix_answer("what changed in python 3.13 docs", plan=plan, llm_draft="It changed a bit.", evidence=bundle)
        self.assertIn("official docs", mixed.lower())
        self.assertNotIn("official docs, (", mixed.lower())
        self.assertIn("October 7, 2024", mixed)
        self.assertIn("interactive interpreter", mixed)
        self.assertIn("free-threaded mode", mixed)
        self.assertNotIn("Â¶", mixed)
        self.assertNotIn("â", mixed)

    def test_docs_answer_uses_selected_page_date_not_neighboring_results(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "what changed in python 3.13 docs", "test", 0.9)
        bundle = SearchBundle(
            query="what changed in python 3.13 docs",
            results=[
                SearchResult(
                    title="What's New In Python 3.13",
                    url="https://docs.python.org/3/whatsnew/3.13.html",
                    snippet=(
                        "Python 3.13 was released on October 7, 2024. "
                        "The biggest changes include a new interactive interpreter, experimental free-threaded mode, and an experimental JIT compiler."
                    ),
                    source_domain="docs.python.org",
                    published_date="2024-10-07",
                ),
                SearchResult(
                    title="What's New In Python 3.5",
                    url="https://docs.python.org/3.13/whatsnew/3.5.html",
                    snippet="Python 3.5 was released on September 13, 2015.",
                    source_domain="docs.python.org",
                    published_date="2015-09-13",
                ),
            ],
        )
        mixed = mix_answer("what changed in python 3.13 docs", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("October 7, 2024", mixed)
        self.assertNotIn("September 13, 2015", mixed)

    def test_who_guidance_answer_prefers_clean_official_lead(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            summary=(
                "10 Jul 2025Ã‚Â·New WHO guidelines for clinical management of arboviral diseases: dengue, chikungunya, Zika and yellow fever ...\n"
                "Supporting sources: Dengue - World Health Organization (WHO); WHO guidelines for clinical management of arboviral diseases"
            ),
            execution_trace=["route: prioritizing official and documentation sources"],
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="10 Jul 2025Ã‚Â·New WHO guidelines for clinical management of arboviral diseases: dengue, chikungunya, Zika and yellow fever ...",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="Dengue - World Health Organization (WHO)",
                    url="https://www.who.int/news-room/fact-sheets/detail/dengue-and-severe-dengue",
                    snippet="WHO dengue fact sheet.",
                    source_domain="who.int",
                    published_date="2025-08-21",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("The latest WHO guidance I found is", mixed)
        self.assertNotIn("Ã‚", mixed)
        self.assertNotIn("Ã¢", mixed)

        self.assertIn("WHO guideline publication", mixed)
        self.assertNotIn("National Guideline", mixed)

    def test_github_answer_filters_generic_blog_sources(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "check out openclaw on github", "test", 0.9)
        bundle = SearchBundle(
            query="check out openclaw on github",
            results=[
                SearchResult(
                    title="OpenClaw - Personal AI Assistant - GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet=(
                        "openclaw/openclaw is a GitHub repository. Default branch: main. "
                        "Detected manifests: package.json, pyproject.toml. "
                        "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
                    ),
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
                SearchResult(
                    title="OpenClaw GitHub Guide: Installation, Setup and Troubleshooting - Bluehost",
                    url="https://www.bluehost.com/blog/openclaw-github-guide/",
                    snippet="Third-party blog guide.",
                    source_domain="bluehost.com",
                ),
                SearchResult(
                    title="Install - OpenClaw",
                    url="https://docs.openclaw.ai/install",
                    snippet="Official install docs.",
                    source_domain="docs.openclaw.ai",
                ),
            ],
        )
        mixed = mix_answer("check out openclaw on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("Bluehost", mixed)
        self.assertIn("Install - OpenClaw", mixed)

    def test_github_answer_prefers_first_party_docs_and_releases_over_third_party_guides(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "check out openclaw on github", "test", 0.9)
        bundle = SearchBundle(
            query="check out openclaw on github",
            summary=(
                "openclaw/openclaw is a GitHub repository. Default branch: main. "
                "Detected manifests: package.json, pyproject.toml. "
                "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
            ),
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet="Repository landing page.",
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
                SearchResult(
                    title="OpenClaw GitHub - Official Repo, Releases & Download Checks",
                    url="https://openclawdocs.com/github/",
                    snippet="Third-party guide site.",
                    source_domain="openclawdocs.com",
                ),
                SearchResult(
                    title="Install - OpenClaw",
                    url="https://docs.openclaw.ai/install",
                    snippet="Official install docs.",
                    source_domain="docs.openclaw.ai",
                ),
                SearchResult(
                    title="Releases for openclaw/openclaw",
                    url="https://github.com/openclaw/openclaw/releases",
                    snippet="Tagged releases.",
                    source_domain="github.com",
                ),
            ],
        )
        mixed = mix_answer("check out openclaw on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("Install - OpenClaw", mixed)
        self.assertIn("Releases for openclaw/openclaw", mixed)
        self.assertNotIn("openclawdocs.com", mixed)
        self.assertNotIn("Official Repo, Releases & Download Checks", mixed)

    def test_github_answer_skips_org_page_for_single_repo_lookup(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "check out openclaw on github", "test", 0.9)
        bundle = SearchBundle(
            query="check out openclaw on github",
            summary=(
                "openclaw/openclaw is a GitHub repository. Default branch: main. "
                "Detected manifests: package.json, pyproject.toml. "
                "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
            ),
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet="Repository landing page.",
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
                SearchResult(
                    title="openclaw·GitHub",
                    url="https://github.com/openclaw",
                    snippet="Organization page.",
                    source_domain="github.com",
                ),
                SearchResult(
                    title="Install - OpenClaw",
                    url="https://docs.openclaw.ai/install",
                    snippet="Official install docs.",
                    source_domain="docs.openclaw.ai",
                ),
            ],
        )
        mixed = mix_answer("check out openclaw on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("Install - OpenClaw", mixed)
        self.assertNotIn("openclaw·GitHub", mixed)
        self.assertNotIn("openclaw?GitHub", mixed)

    def test_github_answer_recovers_repo_details_from_summary_and_uses_clean_source_labels(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "check out openclaw on github", "test", 0.9)
        bundle = SearchBundle(
            query="check out openclaw on github",
            summary=(
                "openclaw/openclaw is a GitHub repository. Default branch: main. "
                "Detected manifests: package.json, pyproject.toml. "
                "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
            ),
            results=[
                SearchResult(
                    title="GitHub - openclaw/openclaw",
                    url="https://github.com/openclaw/openclaw",
                    snippet="Repository landing page.",
                    source_domain="github.com",
                    published_date="2026-03-16",
                ),
                SearchResult(
                    title="Releases Â· openclaw/openclaw",
                    url="https://github.com/openclaw/openclaw/releases",
                    snippet="Tagged releases.",
                    source_domain="github.com",
                ),
            ],
        )
        mixed = mix_answer("check out openclaw on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("Default branch: `main`.", mixed)
        self.assertIn("`package.json`", mixed)
        self.assertIn("Releases for openclaw/openclaw", mixed)
        self.assertNotIn("Releases Â·", mixed)

    def test_docs_answer_support_stays_on_requested_version(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "what changed in python 3.13 docs", "test", 0.9)
        bundle = SearchBundle(
            query="what changed in python 3.13 docs",
            results=[
                SearchResult(
                    title="What's New In Python 3.13",
                    url="https://docs.python.org/3/whatsnew/3.13.html",
                    snippet="Python 3.13 was released on October 7, 2024. Biggest changes include a new interactive interpreter.",
                    source_domain="docs.python.org",
                ),
                SearchResult(
                    title="What's new in Python 3.14 - Python 3.14.3 documentation",
                    url="https://docs.python.org/3/whatsnew/3.14.html",
                    snippet="Python 3.14 changes.",
                    source_domain="docs.python.org",
                ),
            ],
        )
        mixed = mix_answer("what changed in python 3.13 docs", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("3.14", mixed)

    def test_docs_answer_ignores_other_sections_from_same_doc_version(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "what changed in python 3.13 docs", "test", 0.9)
        bundle = SearchBundle(
            query="what changed in python 3.13 docs",
            results=[
                SearchResult(
                    title="What's New In Python 3.13",
                    url="https://docs.python.org/3/whatsnew/3.13.html",
                    snippet="Python 3.13 was released on October 7, 2024. Biggest changes include a new interactive interpreter.",
                    source_domain="docs.python.org",
                ),
                SearchResult(
                    title="2to3 - Automated Python 2 to 3 code translation -",
                    url="https://docs.python.org/3.13/library/2to3.html",
                    snippet="Python 3.13.12 documentation navigation shell.",
                    source_domain="docs.python.org",
                ),
            ],
        )
        mixed = mix_answer("what changed in python 3.13 docs", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("2to3", mixed)

    def test_who_sources_use_clean_display_titles(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            results=[
                SearchResult(
                    title="New WHOguidelinesfor clinical management ofarboviraldiseases...",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="WHOguidelinesfor clinical",
                    url="https://www.who.int/publications/i/item/9789240111110",
                    snippet="WHO publication page.",
                    source_domain="who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("WHO news:", mixed)
        self.assertIn("WHO guideline publication", mixed)
        self.assertNotIn("WHOguidelinesfor", mixed)

    def test_who_answer_sources_skip_country_specific_guidance_pages(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="National Guideline for Clinical Management of Dengue 2022",
                    url="https://www.who.int/timorleste/publications/national-guideline-for-clinical-management-of-dengue-2022",
                    snippet="Country-specific page.",
                    source_domain="who.int",
                ),
                SearchResult(
                    title="WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/publications/i/item/9789240111110",
                    snippet="WHO publication page.",
                    source_domain="who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("WHO guideline publication", mixed)
        self.assertNotIn("Timorleste", mixed)
        self.assertNotIn("National Guideline", mixed)

    def test_who_answer_uses_query_context_to_reject_country_page_when_top_row_is_abbreviated(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            summary=(
                "The World Health Organization (WHO) has published new guidelines to support health-care providers caring for patients "
                "with suspected or confirmed arboviral diseases.\n"
                "Supporting sources: National Guideline for Clinical Management of Dengue 2022"
            ),
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases ...",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="National Guideline for Clinical Management of Dengue 2022",
                    url="https://www.who.int/timorleste/publications/national-guideline-for-clinical-management-of-dengue-2022",
                    snippet="Country-specific page.",
                    source_domain="who.int",
                ),
                SearchResult(
                    title="WHO guidelines for clinical management of arboviral diseases",
                    url="https://iris.who.int/items/095e80fc-c752-4801-b7fe-ba19a24b7659",
                    snippet="WHO guideline publication page.",
                    source_domain="iris.who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("WHO guideline publication", mixed)
        self.assertNotIn("timorleste", mixed.lower())
        self.assertNotIn("National Guideline", mixed)

    def test_who_answer_prefers_canonical_publication_page_over_bitstream_mirrors(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="WHO guideline bitstream",
                    url="https://iris.who.int/server/api/core/bitstreams/634a55a5-327e-459b-a633-0650fe8ad6c9/content",
                    snippet="WHO guideline bitstream.",
                    source_domain="iris.who.int",
                ),
                SearchResult(
                    title="WHO guideline item page",
                    url="https://iris.who.int/items/095e80fc-c752-4801-b7fe-ba19a24b7659",
                    snippet="WHO guideline publication page.",
                    source_domain="iris.who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("iris.who.int/items/095e80fc-c752-4801-b7fe-ba19a24b7659", mixed)
        self.assertIn("- WHO guideline publication: https://iris.who.int/items/095e80fc-c752-4801-b7fe-ba19a24b7659", mixed)
        self.assertNotIn("server/api/core/bitstreams", mixed)

    def test_who_answer_prefers_handle_page_over_bitstream_mirror(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="WHO guideline bitstream",
                    url="https://iris.who.int/server/api/core/bitstreams/634a55a5-327e-459b-a633-0650fe8ad6c9/content",
                    snippet="WHO guideline bitstream.",
                    source_domain="iris.who.int",
                ),
                SearchResult(
                    title="WHO guideline handle page",
                    url="https://iris.who.int/handle/10665/381804",
                    snippet="WHO guideline publication page.",
                    source_domain="iris.who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("iris.who.int/handle/10665/381804", mixed)
        self.assertNotIn("server/api/core/bitstreams", mixed)

    def test_who_answer_prefers_i_item_publication_page_over_b_listing(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "latest WHO dengue treatment guidance", "test", 0.9)
        bundle = SearchBundle(
            query="latest WHO dengue treatment guidance",
            results=[
                SearchResult(
                    title="New WHO guidelines for clinical management of arboviral diseases",
                    url="https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    snippet="WHO news item.",
                    source_domain="who.int",
                    published_date="2025-07-10",
                ),
                SearchResult(
                    title="WHO publication listing",
                    url="https://www.who.int/publications/b/79410",
                    snippet="WHO publication listing page.",
                    source_domain="who.int",
                ),
                SearchResult(
                    title="WHO guideline publication",
                    url="https://www.who.int/publications/i/item/9789240110473",
                    snippet="Canonical WHO publication page.",
                    source_domain="who.int",
                ),
            ],
        )
        mixed = mix_answer("latest WHO dengue treatment guidance", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("https://www.who.int/publications/i/item/9789240110473", mixed)
        self.assertNotIn("https://www.who.int/publications/b/79410", mixed)

    def test_hypertension_answer_uses_clean_primary_guideline_label(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA/SGIM Guideline",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    snippet="Full guideline article.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("2025 ACC/AHA high blood pressure guideline", mixed)
        self.assertNotIn("AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA/SGIM", mixed)

    def test_hypertension_answer_sources_skip_session_and_journal_hubs(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="Hypertension | AHA/ASA Journals",
                    url="https://www.ahajournals.org/hypertension-sessions",
                    snippet="Hypertension sessions landing page.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="American Heart Association Journals",
                    url="https://www.ahajournals.org/journal/hyp",
                    snippet="Journal hub page.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="2025 High Blood Pressure Guideline-at-a-Glance | JACC",
                    url="https://www.jacc.org/doi/10.1016/j.jacc.2025.07.010",
                    snippet="JACC at-a-glance summary of the 2025 high blood pressure guideline.",
                    source_domain="jacc.org",
                    published_date="2025-07-01",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("2025 High Blood Pressure Guideline-at-a-Glance | JACC", mixed)
        self.assertNotIn("Hypertension | AHA/ASA Journals", mixed)
        self.assertNotIn("American Heart Association Journals", mixed)

    def test_hypertension_answer_sources_skip_commentary_style_support_pages(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            summary=(
                "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.\n"
                "Supporting sources: Projected Impact of 2025 AHA/ACC High Blood Pressure Guideline on ...; "
                "Debate on the 2025 Guideline for the Prevention, Detection, Evaluation ..."
            ),
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="Projected Impact of 2025 AHA/ACC High Blood Pressure Guideline on ...",
                    url="https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25464",
                    snippet="Projected impact commentary.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="Debate on the 2025 Guideline for the Prevention, Detection, Evaluation ...",
                    url="https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25466",
                    snippet="Debate article.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA/SGIM Guideline",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    snippet="Full guideline article.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("2025 High Blood Pressure Guidelines - AHA/ASA Journals", mixed)
        self.assertNotIn("Projected Impact", mixed)
        self.assertNotIn("Debate on the 2025 Guideline", mixed)

    def test_hypertension_answer_sources_skip_editors_view_support_pages(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA ...",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    snippet="Full guideline article for high blood pressure.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="Hypertension Editors' View of the 2025 Guideline for the ...",
                    url="https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25467",
                    snippet="Editors' view on the 2025 hypertension guideline.",
                    source_domain="ahajournals.org",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("CIR.0000000000001356", mixed)
        self.assertNotIn("Editors' View", mixed)

    def test_hypertension_answer_support_phrase_stays_on_primary_guideline_sources(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA ...",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    snippet="Full guideline article for high blood pressure.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="Implementing the PREVENT Risk Equation in the 2025 Guideline for the Prevention, Detection, Evaluation, and Management of High Blood Pressure in Adults | Hypertension",
                    url="https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25418",
                    snippet="Implementation-focused support article.",
                    source_domain="ahajournals.org",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("CIR.0000000000001356", mixed)
        self.assertNotIn("Implementing the PREVENT Risk Equation", mixed)

    def test_hypertension_answer_sources_skip_generic_journal_hosts_and_unrelated_dois(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="ahajournals.org/doi/10.1161/CIR.0000000000001309",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309",
                    snippet="2025 ACC/AHA/ACEP guideline for the management of another cardiovascular topic.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="circ.ahajournals.org",
                    url="https://circ.ahajournals.org/",
                    snippet="American Heart Association journal homepage with general guideline links.",
                    source_domain="circ.ahajournals.org",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("CIR.0000000000001309", mixed)
        self.assertNotIn("circ.ahajournals.org", mixed)

    def test_hypertension_answer_sources_dedupe_pdf_and_doi_variants(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", True, None, True, "what are the latest hypertension guidelines", "test", 0.9)
        bundle = SearchBundle(
            query="what are the latest hypertension guidelines",
            results=[
                SearchResult(
                    title="2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    url="https://www.ahajournals.org/guidelines/high-blood-pressure",
                    snippet="The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                    source_domain="ahajournals.org",
                    published_date="2025-08-14",
                ),
                SearchResult(
                    title="2025 AHA/ACC/... Guideline",
                    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    snippet="Full guideline article for high blood pressure.",
                    source_domain="ahajournals.org",
                ),
                SearchResult(
                    title="2025 AHA/ACC/... Guideline PDF",
                    url="https://www.ahajournals.org/doi/pdf/10.1161/CIR.0000000000001356",
                    snippet="PDF version of the same high blood pressure guideline.",
                    source_domain="ahajournals.org",
                ),
            ],
        )
        mixed = mix_answer("what are the latest hypertension guidelines", plan=plan, llm_draft="", evidence=bundle)
        self.assertIn("CIR.0000000000001356", mixed)
        self.assertEqual(mixed.count("CIR.0000000000001356"), 1)

    def test_github_compare_answer_keeps_sources_to_primary_repos(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "compare openclaw and deer-flow on github", "test", 0.9)
        bundle = SearchBundle(
            query="compare openclaw and deer-flow on github",
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet=(
                        "openclaw/openclaw is a GitHub repository. Default branch: main. "
                        "Detected manifests: package.json, pyproject.toml. "
                        "Latest visible commit: 2026-03-16 | 6ba4d0d | fix. "
                        "README excerpt: OpenClaw is a personal AI assistant you run on your own devices."
                    ),
                    source_domain="github.com",
                ),
                SearchResult(
                    title="bytedance/deer-flow on GitHub",
                    url="https://github.com/bytedance/deer-flow",
                    snippet="bytedance/deer-flow is a GitHub repository. Default branch: main.",
                    source_domain="github.com",
                ),
                SearchResult(
                    title="GitHub - Skivmo/Deer_Claw: A hybrid of Open Claw and Deerflow",
                    url="https://github.com/Skivmo/Deer_Claw",
                    snippet="Derivative repository.",
                    source_domain="github.com",
                ),
            ],
        )
        mixed = mix_answer("compare openclaw and deer-flow on github", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("Deer_Claw", mixed)
        self.assertNotIn("... 2026-03-16", mixed)

    def test_github_cleanup_note_does_not_trigger_caution_banner(self) -> None:
        plan = QueryPlan("SEARCH_ONLY", "general", False, None, True, "summarize this https://github.com/openclaw/openclaw", "test", 0.9)
        bundle = SearchBundle(
            query="summarize this https://github.com/openclaw/openclaw",
            warnings=["Temporary repository clone cleaned up after inspection."],
            results=[
                SearchResult(
                    title="openclaw/openclaw on GitHub",
                    url="https://github.com/openclaw/openclaw",
                    snippet="openclaw/openclaw is a GitHub repository. Default branch: main. Detected manifests: package.json, pyproject.toml.",
                    source_domain="github.com",
                    published_date="2026-03-16",
                )
            ],
        )
        mixed = mix_answer("summarize this https://github.com/openclaw/openclaw", plan=plan, llm_draft="", evidence=bundle)
        self.assertNotIn("source freshness or coverage is still a little thin", mixed.lower())


class WebSearchHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_web_prefers_github_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(mode="github", query="openclaw github", query_variants=["site:github.com openclaw"], reason="github_lookup")
        fake_rows = [{"title": "OpenClaw", "url": "https://github.com/openclaw/openclaw", "description": "Repo"}]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_github_browse", AsyncMock(return_value=fake_rows)) as github_mock:
                rows = await handler.search_web("openclaw github")
        github_mock.assert_awaited_once()
        self.assertEqual(rows, fake_rows)

    async def test_github_browse_compare_keeps_only_selected_repo_rows(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="compare openclaw and deer-flow on github",
            query_variants=["compare openclaw and deer-flow on github", "site:github.com openclaw deer-flow"],
            reason="github_lookup",
        )
        discovery = [
            {
                "title": "openclaw/openclaw",
                "url": "https://github.com/openclaw/openclaw",
                "description": "OpenClaw repository.",
                "source": "searxng",
            },
            {
                "title": "bytedance/deer-flow",
                "url": "https://github.com/bytedance/deer-flow",
                "description": "DeerFlow repository.",
                "source": "searxng",
            },
            {
                "title": "Skivmo/Deer_Claw",
                "url": "https://github.com/Skivmo/Deer_Claw",
                "description": "A hybrid repo that should not be appended to the compare answer.",
                "source": "searxng",
            },
        ]
        inspections = [
            GitHubInspection(
                repo_url="https://github.com/openclaw/openclaw",
                repo_slug="openclaw/openclaw",
                default_branch="main",
                latest_commit="2026-03-17",
                readme_excerpt="OpenClaw is a personal AI assistant.",
                manifests={"package.json": "name=openclaw"},
                summary="OpenClaw summary.",
                inspection_method="remote",
            ),
            GitHubInspection(
                repo_url="https://github.com/bytedance/deer-flow",
                repo_slug="bytedance/deer-flow",
                default_branch="main",
                latest_commit="2026-03-17",
                readme_excerpt="DeerFlow is an open-source super agent harness.",
                manifests={},
                summary="DeerFlow summary.",
                inspection_method="remote",
            ),
        ]
        with patch.object(handler, "_should_use_agentpedia_memory", return_value=False):
            with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=discovery)):
                with patch("workshop.toolbox.stacks.web_core.websearch.choose_repositories", return_value=[
                    "https://github.com/openclaw/openclaw",
                    "https://github.com/bytedance/deer-flow",
                ]):
                    with patch("workshop.toolbox.stacks.web_core.websearch.inspect_github_repository", side_effect=inspections):
                        with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                            rows = await handler._github_browse("compare openclaw and deer-flow on github", plan)
        urls = [str((row or {}).get("url") or "") for row in rows]
        self.assertIn("https://github.com/openclaw/openclaw", urls)
        self.assertIn("https://github.com/bytedance/deer-flow", urls)
        self.assertNotIn("https://github.com/Skivmo/Deer_Claw", urls)

    async def test_github_browse_compare_uses_canonical_repos_without_search_discovery(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="check out pytorch versus tensorflow on github",
            query_variants=["check out pytorch versus tensorflow on github", "site:github.com pytorch tensorflow"],
            reason="github_lookup",
        )
        inspections = [
            GitHubInspection(
                repo_url="https://github.com/pytorch/pytorch",
                repo_slug="pytorch/pytorch",
                default_branch="main",
                latest_commit="2026-03-17",
                readme_excerpt="PyTorch is a tensor and deep learning framework.",
                manifests={"pyproject.toml": "name=torch"},
                summary="pytorch/pytorch is a GitHub repository.",
                inspection_method="remote",
            ),
            GitHubInspection(
                repo_url="https://github.com/tensorflow/tensorflow",
                repo_slug="tensorflow/tensorflow",
                default_branch="master",
                latest_commit="2026-03-17",
                readme_excerpt="TensorFlow is an end-to-end open source machine learning platform.",
                manifests={"requirements.txt": "tensorflow"},
                summary="tensorflow/tensorflow is a GitHub repository.",
                inspection_method="remote",
            ),
        ]
        with patch.object(handler, "_should_use_agentpedia_memory", return_value=False):
            with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock()) as search_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.inspect_github_repository", side_effect=inspections) as inspect_mock:
                    with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                        rows = await handler._github_browse("check out pytorch versus tensorflow on github", plan)
        search_mock.assert_not_awaited()
        self.assertTrue(all(call.kwargs.get("remote_only") is True for call in inspect_mock.call_args_list))
        urls = [str((row or {}).get("url") or "") for row in rows]
        self.assertEqual(urls[:2], ["https://github.com/pytorch/pytorch", "https://github.com/tensorflow/tensorflow"])
        steps = list((handler.last_browse_report or {}).get("execution_steps") or [])
        self.assertTrue(any("resolved canonical GitHub comparison subjects without search discovery" in step for step in steps))

    async def test_github_browse_treats_comparison_between_wording_as_compare_mode(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="github comparison between django and fastapi",
            query_variants=["github comparison between django and fastapi", "site:github.com django fastapi"],
            reason="github_lookup",
        )
        inspections = [
            GitHubInspection(
                repo_url="https://github.com/django/django",
                repo_slug="django/django",
                default_branch="main",
                latest_commit="2026-03-17",
                readme_excerpt="Django is a high-level Python web framework.",
                manifests={"pyproject.toml": "name=django"},
                summary="django/django is a GitHub repository.",
                inspection_method="remote",
            ),
            GitHubInspection(
                repo_url="https://github.com/fastapi/fastapi",
                repo_slug="fastapi/fastapi",
                default_branch="master",
                latest_commit="2026-03-16",
                readme_excerpt="FastAPI is a modern, fast web framework for APIs.",
                manifests={"pyproject.toml": "name=fastapi"},
                summary="fastapi/fastapi is a GitHub repository.",
                inspection_method="remote",
            ),
        ]
        with patch.object(handler, "_should_use_agentpedia_memory", return_value=False):
            with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock()) as search_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.inspect_github_repository", side_effect=inspections) as inspect_mock:
                    with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                        rows = await handler._github_browse("github comparison between django and fastapi", plan)
        search_mock.assert_not_awaited()
        self.assertTrue(all(call.kwargs.get("remote_only") is True for call in inspect_mock.call_args_list))
        urls = [str((row or {}).get("url") or "") for row in rows]
        self.assertEqual(urls[:2], ["https://github.com/django/django", "https://github.com/fastapi/fastapi"])

    async def test_direct_url_browse_cleans_python_docs_boilerplate(self) -> None:
        handler = WebSearchHandler()
        url = "https://docs.python.org/3/whatsnew/3.13.html"
        plan = BrowsePlan(mode="direct_url", query=f"summarize this {url}", direct_urls=[url], reason="direct_url")
        extracted = (
            "Python 3.14.3 documentation Theme Auto Light Dark Table of Contents "
            "What's New In Python 3.13 Summary Release Highlights "
            "Python 3.13 was released on October 7, 2024. "
            "Previous topic Installing Python Modules Next topic What's New In Python 3.14"
        )
        with patch("workshop.toolbox.stacks.web_core.websearch._fetch_url_text", AsyncMock(return_value=(url, extracted))):
            rows = await handler._direct_url_browse(f"summarize this {url}", plan)
        self.assertEqual(rows[0]["title"], "What's New In Python 3.13")
        self.assertIn("October 7, 2024", rows[0]["description"])
        self.assertNotIn("Theme Auto Light Dark", rows[0]["description"])
        self.assertNotIn("Table of Contents", rows[0]["description"])
        self.assertNotIn("Previous topic", rows[0]["description"])
        self.assertIn("What's New In Python 3.13", str((handler.last_browse_report or {}).get("summary") or ""))

    async def test_direct_url_browse_cleans_react_blog_root(self) -> None:
        handler = WebSearchHandler()
        url = "https://react.dev/blog"
        plan = BrowsePlan(mode="direct_url", query=f"summarize this {url}", direct_urls=[url], reason="direct_url")
        extracted = "React Blog ? React Blog React Blog This blog is the official source for the updates from the React team."
        with patch("workshop.toolbox.stacks.web_core.websearch._fetch_url_text", AsyncMock(return_value=(url, extracted))):
            rows = await handler._direct_url_browse(f"summarize this {url}", plan)
        self.assertEqual(rows[0]["title"], "React Blog")
        self.assertEqual(rows[0]["description"], "Official React blog page with updates from the React team.")
        self.assertIn("React Blog", str((handler.last_browse_report or {}).get("summary") or ""))

    async def test_direct_url_browse_cleans_mdn_javascript_page(self) -> None:
        handler = WebSearchHandler()
        url = "https://developer.mozilla.org/en-US/docs/Web/JavaScript"
        plan = BrowsePlan(mode="direct_url", query=f"summarize this {url}", direct_urls=[url], reason="direct_url")
        extracted = "developer.mozilla.org JavaScript MDN JavaScript is a scripting language used to create dynamic content on the web."
        with patch("workshop.toolbox.stacks.web_core.websearch._fetch_url_text", AsyncMock(return_value=(url, extracted))):
            rows = await handler._direct_url_browse(f"summarize this {url}", plan)
        self.assertEqual(rows[0]["title"], "JavaScript | MDN Web Docs")
        self.assertEqual(rows[0]["description"], "MDN overview page for JavaScript guides, references, and tutorials.")
        self.assertIn("JavaScript", str((handler.last_browse_report or {}).get("summary") or ""))

    async def test_summarize_result_rows_uses_clean_support_titles_for_who_guidance(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "latest WHO dengue treatment guidance",
            [
                {
                    "title": "New WHO guidelines for clinical management of arboviral diseases",
                    "url": "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    "description": "WHO published new clinical management guidance.",
                },
                {
                    "title": "National Guideline for Clinical Management of Dengue 2022",
                    "url": "https://www.who.int/timorleste/publications/national-guideline-for-clinical-management-of-dengue-2022",
                    "description": "Country-specific WHO page.",
                },
                {
                    "title": "WHO guideline item page",
                    "url": "https://iris.who.int/handle/10665/381804",
                    "description": "Canonical WHO publication.",
                },
            ],
        )
        self.assertIn("Supporting sources: WHO guideline publication", summary)
        self.assertNotIn("National Guideline", summary)

    async def test_summarize_result_rows_uses_clean_support_titles_for_hypertension(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "what are the latest hypertension guidelines",
            [
                {
                    "title": "2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    "url": "https://www.ahajournals.org/guidelines/high-blood-pressure",
                    "description": "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                },
                {
                    "title": "2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA/SGIM Guideline",
                    "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    "description": "Full guideline article.",
                },
                {
                    "title": "Projected Impact of 2025 AHA/ACC High Blood Pressure Guideline on ...",
                    "url": "https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25464",
                    "description": "Projected impact commentary.",
                },
            ],
        )
        self.assertIn("Supporting sources: 2025 ACC/AHA high blood pressure guideline", summary)
        self.assertNotIn("Projected Impact", summary)

    async def test_summarize_result_rows_falls_back_to_clean_title_when_summary_text_is_mashed(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "what are the latest hypertension guidelines",
            [
                {
                    "title": "2025 High Blood Pressure Guidelines - AHA/ASA Journals",
                    "url": "https://www.ahajournals.org/guidelines/high-blood-pressure",
                    "description": "The2025AHA/ACCHighBloodPressureGuidelinereflects the latest recommendations.",
                },
                {
                    "title": "2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA/SGIM Guideline",
                    "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                    "description": "Full guideline article.",
                },
            ],
        )
        self.assertTrue(summary.startswith("2025 High Blood Pressure Guidelines"))
        self.assertNotIn("The2025AHA/ACC", summary)

    async def test_extract_cardio_primary_guideline_candidate_prefers_full_guideline_link(self) -> None:
        handler = WebSearchHandler()
        html = """
        <html><body>
        <a href="/doi/10.1161/HYPERTENSIONAHA.125.25418">Implementing the 2025 Guideline</a>
        <a href="/doi/10.1161/CIR.0000000000001356">Full guideline for high blood pressure</a>
        </body></html>
        """
        candidate = handler._extract_cardio_primary_guideline_candidate(
            html,
            "https://www.ahajournals.org/guidelines/high-blood-pressure",
        )
        self.assertIsNotNone(candidate)
        self.assertIn("CIR.0000000000001356", str((candidate or {}).get("url") or ""))

    async def test_promote_cardio_primary_guideline_adds_primary_row_from_hub(self) -> None:
        handler = WebSearchHandler()
        seed_rows = [
            {
                "title": "2025 High Blood Pressure Guidelines",
                "url": "https://www.ahajournals.org/guidelines/high-blood-pressure",
                "description": "Official guideline hub.",
                "content": "Official high blood pressure hub page.",
            },
            {
                "title": "Implementing the 2025 Guideline for the Prevention, Detection, Evaluation, and Management of High Blood Pressure in Adults",
                "url": "https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25418",
                "description": "Commentary article.",
            },
        ]

        class _FakeResponse:
            text = '<a href="/doi/10.1161/CIR.0000000000001356">Full guideline for high blood pressure</a>'
            url = "https://www.ahajournals.org/guidelines/high-blood-pressure"

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                return _FakeResponse()

        enriched_primary = [
            {
                "title": "2025 ACC/AHA high blood pressure guideline",
                "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356",
                "description": "Primary guideline article.",
                "content": "Full guideline article.",
                "source": "cardio_official_adapter",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.httpx.AsyncClient", return_value=_FakeClient()):
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=enriched_primary)):
                promoted = await handler._promote_cardio_primary_guideline(
                    "what are the latest hypertension guidelines",
                    seed_rows,
                    mode="deep",
                )
        self.assertEqual(promoted[0]["url"], "https://www.ahajournals.org/guidelines/high-blood-pressure")
        self.assertEqual(promoted[1]["url"], "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356")
        self.assertTrue(any("promoted the primary ACC/AHA guideline article" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_promote_cardio_primary_guideline_recovers_primary_from_targeted_search_when_hub_fetch_blocked(self) -> None:
        handler = WebSearchHandler()
        seed_rows = [
            {
                "title": "2025 High Blood Pressure Guidelines",
                "url": "https://www.ahajournals.org/guidelines/high-blood-pressure",
                "description": "Official guideline hub.",
                "content": "Official high blood pressure hub page.",
            },
            {
                "title": "Implementing the 2025 Guideline for the Prevention, Detection, Evaluation, and Management of High Blood Pressure in Adults",
                "url": "https://www.ahajournals.org/doi/10.1161/HYPERTENSIONAHA.125.25418",
                "description": "Commentary article.",
            },
        ]

        class _BlockedResponse:
            status_code = 403
            text = "<html><title>Attention Required!</title><body>Cloudflare bot verification</body></html>"
            url = "https://www.ahajournals.org/guidelines/high-blood-pressure"

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                return _BlockedResponse()

        recovered_rows = [
            {
                "title": "2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA Guideline",
                "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356?url_ver=Z39.88-2003",
                "description": "Primary guideline article.",
                "source": "searxng",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.httpx.AsyncClient", return_value=_FakeClient()):
            with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=recovered_rows)) as search_mock:
                promoted = await handler._promote_cardio_primary_guideline(
                    "what are the latest hypertension guidelines",
                    seed_rows,
                    mode="deep",
                )
        self.assertTrue(search_mock.await_count >= 1)
        self.assertEqual(promoted[1]["url"], "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001356")
        steps = list((handler.last_browse_report or {}).get("execution_steps") or [])
        self.assertTrue(any("official guideline hub fetch looked blocked" in step for step in steps))
        self.assertTrue(any("recovered the primary ACC/AHA guideline article" in step for step in steps))

    def test_official_page_fetch_blocked_detects_challenge_response(self) -> None:
        handler = WebSearchHandler()

        class _BlockedResponse:
            status_code = 403
            text = "<html><body>Just a moment... Cloudflare</body></html>"

        self.assertTrue(handler._official_page_fetch_blocked(_BlockedResponse()))

    async def test_search_routes_github_queries_to_search_web_before_research(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(mode="github", query="summarize this https://github.com/openclaw/openclaw", query_variants=["openclaw/openclaw"], reason="direct_url_input")
        fake_rows = [{"title": "OpenClaw", "url": "https://github.com/openclaw/openclaw", "description": "Repo"}]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=fake_rows)) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[])) as research_mock:
                    rows = await handler.search("summarize this https://github.com/openclaw/openclaw")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertEqual(rows[0]["url"], "https://github.com/openclaw/openclaw")

    async def test_search_routes_official_queries_to_search_web_before_research(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest ACC/AHA hypertension guideline",
            query_variants=["latest ACC/AHA hypertension guideline"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [{"title": "Official guideline", "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356", "description": "Guideline"}]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=fake_rows)) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[])) as research_mock:
                    rows = await handler.search("latest ACC/AHA hypertension guideline")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertIn("ahajournals.org", rows[0]["url"])

    async def test_search_routes_shopping_compare_queries_to_search_web_before_research(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="should I buy Kindle Paperwhite or Kobo Clara",
            query_variants=["Kindle Paperwhite vs Kobo Clara"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [{"title": "Kindle Paperwhite vs Kobo Clara", "url": "https://example.com/compare", "description": "Comparison"}]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=fake_rows)) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[])) as research_mock:
                    rows = await handler.search("should I buy Kindle Paperwhite or Kobo Clara")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertEqual(rows[0]["url"], "https://example.com/compare")

    async def test_search_stops_after_empty_shopping_compare_fast_path(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="should I buy Kindle Paperwhite or Kobo Clara",
            query_variants=["Kindle Paperwhite vs Kobo Clara"],
            reason="freshness_or_depth_needed",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=[])) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[{"title": "slow fallback"}])) as research_mock:
                    rows = await handler.search("should I buy Kindle Paperwhite or Kobo Clara")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertEqual(rows, [])

    async def test_search_routes_software_changelog_queries_to_search_web_before_research(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="summarize kubernetes 1.32 changelog",
            query_variants=["site:kubernetes.io kubernetes 1.32 changelog"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [{"title": "Kubernetes v1.32", "url": "https://kubernetes.io/blog/2025/01/08/kubernetes-v1-32-release/", "description": "Release notes"}]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=fake_rows)) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[])) as research_mock:
                    rows = await handler.search("summarize kubernetes 1.32 changelog")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertIn("kubernetes.io", rows[0]["url"])

    async def test_search_routes_travel_lookup_queries_to_search_web_before_research(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="what to do in Costa Rica",
            query_variants=["Costa Rica things to do", "Costa Rica travel guide"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Costa Rica travel guide",
                "url": "https://www.lonelyplanet.com/costa-rica",
                "description": "Things to do in Costa Rica.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "search_web", AsyncMock(return_value=fake_rows)) as search_web_mock:
                with patch.object(handler, "_research_stack", AsyncMock(return_value=[])) as research_mock:
                    rows = await handler.search("what to do in Costa Rica")
        search_web_mock.assert_awaited_once()
        research_mock.assert_not_called()
        self.assertIn("lonelyplanet.com", rows[0]["url"])

    async def test_deep_browse_prefers_official_search_path(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest ACC/AHA hypertension guideline",
            query_variants=["latest ACC/AHA hypertension guideline", "site:acc.org latest ACC/AHA hypertension guideline"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "2025 High Blood Pressure Guidelines",
                "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                "description": "Official guideline page.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.research_compose", AsyncMock()) as compose_mock:
                    rows = await handler._deep_browse("latest ACC/AHA hypertension guideline", plan)
        self.assertTrue(search_mock.await_count >= 1)
        fetch_mock.assert_awaited_once()
        compose_mock.assert_not_awaited()
        self.assertIn("ahajournals.org", rows[0]["url"])

    async def test_search_web_uses_direct_python_docs_adapter_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="what changed in python 3.13 docs",
            query_variants=["site:docs.python.org What's New In Python 3.13"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "What's New In Python 3.13",
                "url": "https://docs.python.org/3/whatsnew/3.13.html",
                "description": "Official What's New page.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_python_docs_direct_browse", AsyncMock(return_value=fake_rows)) as docs_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("what changed in python 3.13 docs")
        docs_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertEqual(rows[0]["url"], "https://docs.python.org/3/whatsnew/3.13.html")

    async def test_search_web_uses_direct_python_docs_adapter_for_release_notes_query(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest python 3.13 release notes",
            query_variants=["site:docs.python.org What's New In Python 3.13"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "What's New In Python 3.13",
                "url": "https://docs.python.org/3/whatsnew/3.13.html",
                "description": "Official What's New page.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_python_docs_direct_browse", AsyncMock(return_value=fake_rows)) as docs_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("latest python 3.13 release notes")
        docs_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertEqual(rows[0]["url"], "https://docs.python.org/3/whatsnew/3.13.html")

    async def test_search_web_uses_trip_planning_fast_path_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="plan a 3 day trip to Tokyo",
            query_variants=["3 day Tokyo itinerary", "Tokyo itinerary 3 days"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Perfect Tokyo 3 Day Itinerary",
                "url": "https://www.japan-guide.com/e/e3051_tokyo.html",
                "description": "A three-day Tokyo itinerary with neighborhoods and attractions.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_trip_planning_browse", AsyncMock(return_value=fake_rows)) as trip_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("plan a 3 day trip to Tokyo")
        trip_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertIn("japan-guide.com", rows[0]["url"])

    async def test_search_web_uses_travel_lookup_fast_path_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="best time to visit Tokyo",
            query_variants=["best time to visit Tokyo", "Tokyo weather seasons"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Best Time to Visit Tokyo | Japan-Guide",
                "url": "https://www.japan-guide.com/e/e2273.html",
                "description": "Month-by-month guidance on the best time to visit Tokyo.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_travel_lookup_browse", AsyncMock(return_value=fake_rows)) as travel_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("best time to visit Tokyo")
        travel_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertIn("japan-guide.com", rows[0]["url"])

    async def test_search_web_routes_explicit_news_queries_to_news_shortlist_path(self) -> None:
        handler = WebSearchHandler()
        fake_rows = [
            {
                "title": "Inflation news | Reuters",
                "url": "https://www.reuters.com/world/us/",
                "description": "Latest inflation coverage.",
            }
        ]
        with patch.object(handler, "_news_lookup_browse", AsyncMock(return_value=fake_rows)) as news_mock:
            with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                rows = await handler.search_web("latest inflation news")
        news_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertEqual(rows[0]["category"], "news")

    async def test_search_web_routes_budget_travel_queries_to_lookup_fast_path_before_trip_planning(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="budget for 4 days in Paris",
            query_variants=["Paris travel cost", "Paris budget guide"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Paris travel cost guide",
                "url": "https://www.budgetyourtrip.com/france/paris",
                "description": "Average daily cost in Paris.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_travel_lookup_browse", AsyncMock(return_value=fake_rows)) as lookup_mock:
                with patch.object(handler, "_trip_planning_browse", AsyncMock(return_value=[])) as trip_mock:
                    rows = await handler.search_web("budget for 4 days in Paris")
        lookup_mock.assert_awaited_once()
        trip_mock.assert_not_called()
        self.assertIn("budgetyourtrip.com", rows[0]["url"])

    async def test_news_lookup_browse_filters_rows_that_only_mention_topic_in_snippet(self) -> None:
        handler = WebSearchHandler()
        searx_rows = [
            {
                "title": "Texas Roadhouse: Its Valuation Is Still Overcooked",
                "url": "https://seekingalpha.com/article/4883409-texas-roadhouse-stock-valuation-remains-stretched",
                "description": "Margins are being squeezed by inflation.",
                "source": "searxng_news",
            },
            {
                "title": "Inflation cools again as consumer prices ease in latest report",
                "url": "https://www.reuters.com/world/us/inflation-cools-consumer-prices-ease-2026-03-17/",
                "description": "Reuters coverage of the latest inflation report.",
                "source": "searxng_news",
            },
        ]
        with patch.object(handler.news_handler, "_searx_news", AsyncMock(return_value=searx_rows)):
            rows = await handler._news_lookup_browse("latest inflation news", retries=1, backoff_factor=0.1)
        self.assertEqual(len(rows), 1)
        self.assertIn("reuters.com", rows[0]["url"])

    async def test_news_lookup_browse_uses_site_filtered_host_fallback_for_topical_queries(self) -> None:
        handler = WebSearchHandler()
        weak_rows = [
            {
                "title": "Texas Roadhouse: Its Valuation Is Still Overcooked",
                "url": "https://seekingalpha.com/article/4883409-texas-roadhouse-stock-valuation-remains-stretched",
                "description": "Margins are being squeezed by inflation.",
                "source": "searxng_news",
            }
        ]
        fallback_rows = [
            {
                "title": "US inflation isn't subsiding. It's heating up again | Reuters",
                "url": "https://www.reuters.com/markets/us-inflation-isnt-subsiding-its-heating-up-again-2026-02-05/",
                "description": "Reuters coverage of US inflation.",
            },
            {
                "title": "Inflation measure falls to nearly five-year low as gas prices fall and rents cool",
                "url": "https://apnews.com/article/inflation-trump-economy-prices-d489cfa4b48e32232f136830333d1db0",
                "description": "AP coverage of the latest inflation measure.",
            },
        ]
        with patch.object(handler.news_handler, "_searx_news", AsyncMock(return_value=weak_rows)):
            with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=fallback_rows)) as ddg_mock:
                with patch.object(handler.news_handler, "search_news", AsyncMock(return_value=[])) as search_news_mock:
                    rows = await handler._news_lookup_browse("latest inflation news", retries=1, backoff_factor=0.1)
        ddg_mock.assert_awaited_once()
        search_news_mock.assert_not_awaited()
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(host in rows[0]["url"] for host in ("reuters.com", "apnews.com")))

    async def test_news_lookup_browse_requires_reputable_hosts_for_economic_topics(self) -> None:
        handler = WebSearchHandler()
        weak_rows = [
            {
                "title": "Worse than inflation: BofA lays out a disruptive scenario that markets haven't priced in yet",
                "url": "https://finance.yahoo.com/news/worse-inflation-bofa-lays-disruptive-152203726.html",
                "description": "A finance-yahoo business piece mentioning inflation.",
                "source": "searxng_news",
            },
            {
                "title": "Will the Fed Sink Stocks as the Oil Surge Cancels Rate Cuts?",
                "url": "https://www.tastylive.com/news-insights/will-the-fed-sink-stocks-as-the-oil-surge-cancels-rate-cuts",
                "description": "Markets look to the FOMC meeting for direction cues.",
                "source": "searxng_news",
            },
        ]
        fallback_rows = [
            {
                "title": "US inflation isn't subsiding. It's heating up again | Reuters",
                "url": "https://www.reuters.com/markets/us-inflation-isnt-subsiding-its-heating-up-again-2026-02-05/",
                "description": "Reuters coverage of US inflation.",
            }
        ]
        with patch.object(handler.news_handler, "_searx_news", AsyncMock(return_value=weak_rows)):
            with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=fallback_rows)) as ddg_mock:
                rows = await handler._news_lookup_browse("latest inflation news", retries=1, backoff_factor=0.1)
        ddg_mock.assert_awaited_once()
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("reuters.com", rows[0]["url"])

    async def test_news_lookup_browse_requires_reputable_hosts_for_ai_topics(self) -> None:
        handler = WebSearchHandler()
        weak_rows = [
            {
                "title": "1 Artificial Intelligence (AI) Stock That Could Surprise Investors in 2026",
                "url": "https://finance.yahoo.com/news/artificial-intelligence-ai-stock-surprise-investors-2026.html",
                "description": "Finance Yahoo investor-angle AI story.",
                "source": "searxng_news",
            },
            {
                "title": "Lenovo's AI workmate concept is a cross between Wall-E and a lamp",
                "url": "https://www.msn.com/en-us/news/technology/lenovo-ai-workmate-concept/ar-AA123456",
                "description": "MSN syndication of an AI gadget story.",
                "source": "searxng_news",
            },
        ]
        fallback_rows = [
            {
                "title": "OpenAI launches new enterprise AI features | Reuters",
                "url": "https://www.reuters.com/technology/openai-launches-new-enterprise-ai-features-2026-03-17/",
                "description": "Reuters coverage of AI product news.",
            }
        ]
        with patch.object(handler.news_handler, "_searx_news", AsyncMock(return_value=weak_rows)):
            with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=fallback_rows)) as ddg_mock:
                rows = await handler._news_lookup_browse("latest artificial intelligence news", retries=1, backoff_factor=0.1)
        ddg_mock.assert_awaited_once()
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("reuters.com", rows[0]["url"])

    async def test_news_prioritization_for_latest_queries_penalizes_stale_ai_roundups(self) -> None:
        handler = WebSearchHandler()
        stale = {
            "title": "In 2024, artificial intelligence was all about putting AI tools to work",
            "url": "https://apnews.com/article/ai-artificial-intelligence-0b6ab89193265c3f60f382bae9bbabc9",
            "description": "A 2024 AP roundup about artificial intelligence.",
        }
        fresh = {
            "title": "OpenAI launches new enterprise AI features | Reuters",
            "url": "https://www.reuters.com/technology/openai-launches-new-enterprise-ai-features-2026-03-17/",
            "description": "16 hours ago Reuters coverage of AI product news.",
        }
        stale_score = handler._news_row_focus_score("latest artificial intelligence news", stale)
        fresh_score = handler._news_row_focus_score("latest artificial intelligence news", fresh)
        self.assertGreater(fresh_score, stale_score)

    async def test_news_result_rows_adequate_requires_recent_signal_for_latest_queries(self) -> None:
        handler = WebSearchHandler()
        stale_rows = [
            {
                "title": "Artificial intelligence raises risk of extinction, experts say in new warning",
                "url": "https://apnews.com/article/ai-risk-extinction-warning-demo",
                "description": "AP feature page without a fresh recency marker.",
            },
            {
                "title": "Artificial Intelligence (AI) - TechCrunch",
                "url": "https://techcrunch.com/tag/artificial-intelligence/",
                "description": "Topic hub for artificial intelligence coverage.",
            },
        ]
        self.assertFalse(handler._news_result_rows_adequate("latest artificial intelligence news", stale_rows))

    async def test_latest_news_hub_top_row_is_not_adequate(self) -> None:
        handler = WebSearchHandler()
        rows = [
            {
                "title": "Climate Change News | Today's Latest Stories | Reuters",
                "url": "https://www.reuters.com/world/climate-change/",
                "description": "Reuters.com is your online source for the latest news stories and current events.",
            },
            {
                "title": "Climate change: World's glaciers melting faster than ever recorded - BBC",
                "url": "https://www.bbc.com/news/articles/climate-glaciers-2026-03-17",
                "description": "17 March 2026 Glaciers are melting faster than ever recorded under the impact of climate change.",
            },
        ]
        self.assertFalse(handler._news_result_rows_adequate("top climate change stories right now", rows))

    async def test_news_hub_pages_do_not_outrank_recent_articles_for_latest_queries(self) -> None:
        handler = WebSearchHandler()
        hub = {
            "title": "AI News & Artificial Intelligence | TechCrunch",
            "url": "https://techcrunch.com/tag/artificial-intelligence/",
            "description": "Read the latest on artificial intelligence and machine learning tech today.",
        }
        recent_article = {
            "title": "California could be first state to make law schools teach AI | Reuters",
            "url": "https://www.reuters.com/legal/government/california-could-be-first-state-make-law-schools-teach-ai-2026-03-16/",
            "description": "1 day ago California-accredited law schools could soon be required to train students on artificial intelligence.",
        }
        self.assertTrue(handler._news_row_is_hub_page(hub))
        self.assertFalse(handler._news_row_has_recency_signal("latest artificial intelligence news", hub))
        self.assertGreater(
            handler._news_row_focus_score("latest artificial intelligence news", recent_article),
            handler._news_row_focus_score("latest artificial intelligence news", hub),
        )

    async def test_latest_climate_news_reputable_hosts_include_reuters_and_bbc(self) -> None:
        handler = WebSearchHandler()
        hosts = handler._news_reputable_hosts("latest climate change news")
        self.assertIn("reuters.com", hosts)
        self.assertIn("bbc.com", hosts)

    async def test_latest_climate_news_penalizes_bing_advertorial_row(self) -> None:
        handler = WebSearchHandler()
        bing_row = {
            "title": "Climate Change Effects - What Is Climate Change?",
            "url": "https://www.bing.com/search?q=climate+change",
            "description": "We Partner With Leaders For Just & Meaningful Impact To Address The Climate Crisis. Read More Today.",
        }
        reuters_row = {
            "title": "Climate crossroads: a decade after the Paris Agreement | Reuters",
            "url": "https://www.reuters.com/world/climate/climate-crossroads-decade-after-paris-agreement-2026-02-16/",
            "description": "Feb 16, 2026 Ten years after the Paris Agreement took effect, new climate datasets show warming accelerating.",
        }
        self.assertTrue(handler._news_row_looks_evergreen_or_ad("latest climate change news", bing_row))
        self.assertGreater(
            handler._news_row_focus_score("latest climate change news", reuters_row),
            handler._news_row_focus_score("latest climate change news", bing_row),
        )

    async def test_latest_climate_news_penalizes_evergreen_explainer(self) -> None:
        handler = WebSearchHandler()
        explainer = {
            "title": "What is climate change? A really simple guide - BBC",
            "url": "https://www.bbc.com/news/science-environment-24021772",
            "description": "What is climate change? Climate change is the long-term shift in average temperatures and weather conditions.",
        }
        recent_article = {
            "title": "Climate change: World's glaciers melting faster than ever recorded - BBC",
            "url": "https://www.bbc.com/news/articles/climate-glaciers-2026-03-17",
            "description": "17 March 2026 Glaciers are melting faster than ever recorded under the impact of climate change.",
        }
        self.assertTrue(handler._news_row_looks_evergreen_or_ad("climate change headlines today", explainer))
        self.assertGreater(
            handler._news_row_focus_score("climate change headlines today", recent_article),
            handler._news_row_focus_score("climate change headlines today", explainer),
        )

    async def test_latest_climate_news_site_filtered_queries_preserve_today_context(self) -> None:
        handler = WebSearchHandler()
        queries = handler._news_site_filtered_queries("what happened with climate change today")
        self.assertIn("site:reuters.com climate change headlines today", queries)
        self.assertIn("site:apnews.com climate change headlines today", queries)
        self.assertIn('site:reuters.com "climate change" today', queries)

    async def test_latest_climate_news_site_filtered_queries_fan_out_across_hosts_first(self) -> None:
        handler = WebSearchHandler()
        queries = handler._news_site_filtered_queries("what happened with climate change today")
        self.assertEqual(
            queries[:4],
            [
                "site:reuters.com climate change headlines today",
                "site:apnews.com climate change headlines today",
                "site:bbc.com climate change headlines today",
                "site:theguardian.com climate change headlines today",
            ],
        )

    async def test_latest_climate_news_prefers_exact_phrase_over_climate_only_titles(self) -> None:
        handler = WebSearchHandler()
        exact_phrase_row = {
            "title": "Climate change impacts push insurers to rethink flood coverage | Reuters",
            "url": "https://www.reuters.com/world/climate/climate-change-insurers-flood-coverage-2026-03-18/",
            "description": "Mar 18, 2026 Reuters examines how climate change is reshaping insurance exposure.",
        }
        climate_only_row = {
            "title": "Climate crossroads: a decade after the Paris Agreement | Reuters",
            "url": "https://www.reuters.com/world/climate/climate-crossroads-decade-after-paris-agreement-2026-02-16/",
            "description": "Feb 16, 2026 Ten years after the Paris Agreement took effect, new climate datasets show warming accelerating.",
        }
        self.assertGreater(
            handler._news_row_focus_score("latest climate change news", exact_phrase_row),
            handler._news_row_focus_score("latest climate change news", climate_only_row),
        )

    async def test_latest_climate_news_shortlist_drops_evergreen_when_recent_rows_exist(self) -> None:
        handler = WebSearchHandler()
        explainer = {
            "title": "What is climate change? A really simple guide - BBC",
            "url": "https://www.bbc.com/news/science-environment-24021772",
            "description": "What is climate change? Climate change is the long-term shift in average temperatures and weather conditions.",
        }
        recent_article = {
            "title": "Climate crossroads: a decade after the Paris Agreement | Reuters",
            "url": "https://www.reuters.com/world/climate/climate-crossroads-decade-after-paris-agreement-2026-02-16/",
            "description": "Feb 16, 2026 Ten years after the Paris Agreement took effect, new climate datasets show warming accelerating.",
        }
        refined = handler._refine_latest_news_shortlist("what happened with climate change today", [explainer, recent_article])
        self.assertEqual(refined[0]["url"], recent_article["url"])
        self.assertNotIn(explainer["url"], [str((row or {}).get("url") or "") for row in refined])

    async def test_latest_climate_news_reuters_latest_stories_page_counts_as_hub(self) -> None:
        handler = WebSearchHandler()
        hub_row = {
            "title": "Climate Change News | Today's Latest Stories | Reuters",
            "url": "https://www.reuters.com/world/climate-change/",
            "description": "Reuters.com is your online source for the latest news stories and current events.",
        }
        article_row = {
            "title": "Climate crossroads: a decade after the Paris Agreement | Reuters",
            "url": "https://www.reuters.com/world/climate/climate-crossroads-decade-after-paris-agreement-2026-02-16/",
            "description": "Feb 16, 2026 Ten years after the Paris Agreement took effect, new climate datasets show warming accelerating.",
        }
        self.assertTrue(handler._news_row_is_hub_page(hub_row))
        self.assertFalse(handler._news_row_is_hub_page(article_row))

    async def test_summary_source_title_falls_back_to_url_slug_when_title_is_mashed(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "quick summary of how much protein do I need per day",
            [
                {
                    "title": "Howmuchproteindoyouneedeveryday? - Harvard Health",
                    "url": "https://www.health.harvard.edu/blog/how-much-protein-do-you-need-every-day-201506188096",
                    "description": "",
                }
            ],
        )
        self.assertIn("How Much Protein Do You Need Every Day", summary)
        self.assertNotIn("Howmuchproteindoyouneedeveryday", summary)

    async def test_shopping_compare_prioritization_penalizes_stale_roundups(self) -> None:
        handler = WebSearchHandler()
        rows = [
            {
                "title": "MacBook Air vs Dell XPS 13: the best laptops on Earth go head-to-head",
                "url": "https://www.techradar.com/versus/macbook-air-vs-dell-xps-13",
                "description": "Nov 12, 2022 comparison roundup updated with Apple MacBook Air (M3, 2024) and Dell XPS 13 (2024) context.",
            },
            {
                "title": "Dell XPS 13 (2024) vs Apple MacBook Air 13 (M3, 2024)",
                "url": "https://www.rtings.com/laptop/tools/compare/dell-xps-13-2024-vs-apple-macbook-air-13-m3-2024/49547/56059",
                "description": "Oct 8, 2025 side-by-side review.",
            },
        ]
        prioritized = handler._prioritize_browse_rows("pros and cons of MacBook Air vs Dell XPS 13", rows, prefer_official=False)
        self.assertIn("rtings.com", prioritized[0]["url"])

    async def test_shopping_compare_prioritization_penalizes_multi_product_showdowns(self) -> None:
        handler = WebSearchHandler()
        rows = [
            {
                "title": "2025 ultrabook showdown: MacBook Air M4 vs Dell XPS 13 vs Asus Zenbook S 14",
                "url": "https://ts2.tech/en/2025-ultrabook-showdown-macbook-air-m4-vs-dell-xps-13-vs-asus-zenbook-s-14/",
                "description": "2025 ultrabook showdown covering Apple, Dell, and Asus.",
            },
            {
                "title": "Dell XPS 13 (2024) vs Apple MacBook Air 13 (M3, 2024)",
                "url": "https://www.rtings.com/laptop/tools/compare/dell-xps-13-2024-vs-apple-macbook-air-13-m3-2024/49547/56059",
                "description": "Oct 8, 2025 side-by-side review.",
            },
        ]
        prioritized = handler._prioritize_browse_rows("pros and cons of MacBook Air vs Dell XPS 13", rows, prefer_official=False)
        self.assertIn("rtings.com", prioritized[0]["url"])

    async def test_shopping_compare_browse_uses_trusted_review_fallback_when_shortlist_is_noisy(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="pros and cons of MacBook Air vs Dell XPS 13",
            query_variants=[
                "pros and cons of MacBook Air vs Dell XPS 13",
                "MacBook Air vs Dell XPS 13",
            ],
            reason="freshness_or_depth_needed",
        )
        noisy_rows = [
            {
                "title": "MacBook Air vs Dell XPS 13: the best laptops on Earth go head-to-head",
                "url": "https://www.techradar.com/versus/macbook-air-vs-dell-xps-13",
                "description": "Nov 12, 2022 comparison roundup updated with Apple MacBook Air (M3, 2024) and Dell XPS 13 (2024) context.",
            },
            {
                "title": "2025 Best Lightweight Laptops to Buy: MacBook Air M3 vs Dell XPS 13",
                "url": "https://superiptv.online/computer-accessorie/laptops/2025-best-lightweight-laptops-to-buy-macbook-air-m3-vs-dell-xps-13.html",
                "description": "Comparison of lightweight laptops with Apple and Dell.",
            },
        ]
        trusted_rows = [
            {
                "title": "Dell XPS 13 (2024) vs Apple MacBook Air 13 (M3, 2024)",
                "url": "https://www.rtings.com/laptop/tools/compare/dell-xps-13-2024-vs-apple-macbook-air-13-m3-2024/49547/56059",
                "description": "Oct 8, 2025 side-by-side review.",
            }
        ]
        with patch.object(handler, "_variant_ddg_rows", AsyncMock(side_effect=[noisy_rows, trusted_rows])) as ddg_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(side_effect=lambda rows, **_: rows)):
                rows = await handler._shopping_compare_browse("pros and cons of MacBook Air vs Dell XPS 13", plan)
        self.assertGreaterEqual(ddg_mock.await_count, 2)
        self.assertIn("rtings.com", rows[0]["url"])

    async def test_shopping_compare_browse_skips_enrichment_for_ereader_queries(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="should I buy Kindle Paperwhite or Kobo Clara",
            query_variants=[
                "should I buy Kindle Paperwhite or Kobo Clara",
                "Kindle Paperwhite vs Kobo Clara",
            ],
            reason="freshness_or_depth_needed",
        )
        rows = [
            {
                "title": "Kindle Paperwhite vs Kobo Clara: Which is the better e-reader?",
                "url": "https://www.tomsguide.com/versus/kindle-paperwhite-vs-kobo-clara",
                "description": "2025 comparison of Kindle Paperwhite and Kobo Clara.",
            }
        ]
        with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=rows)):
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(side_effect=AssertionError("should not enrich ereader compares"))):
                result = await handler._shopping_compare_browse("should I buy Kindle Paperwhite or Kobo Clara", plan)
        self.assertEqual(result[0]["url"], rows[0]["url"])

    async def test_shopping_compare_browse_mixes_generic_and_trusted_queries_for_ereaders(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="difference between Kindle Paperwhite and Kobo Clara",
            query_variants=["Kindle Paperwhite vs Kobo Clara", "Kindle Paperwhite Kobo Clara comparison"],
            reason="freshness_or_depth_needed",
        )
        trusted_queries = [
            "site:the-ebook-reader.com Kindle Paperwhite vs Kobo Clara",
            "site:tomsguide.com Kindle Paperwhite vs Kobo Clara",
        ]
        rows = [
            {
                "title": "Kindle Paperwhite vs Kobo Clara: Which is the better e-reader?",
                "url": "https://www.tomsguide.com/versus/kindle-paperwhite-vs-kobo-clara",
                "description": "2025 comparison of Kindle Paperwhite and Kobo Clara.",
            }
        ]
        with patch.object(handler, "_shopping_compare_site_filtered_queries", return_value=trusted_queries):
            with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=rows)) as ddg_mock:
                with patch.object(handler, "_fetch_and_attach_content", AsyncMock(side_effect=AssertionError("should not enrich ereader compares"))):
                    result = await handler._shopping_compare_browse("difference between Kindle Paperwhite and Kobo Clara", plan)
        self.assertEqual(result[0]["url"], rows[0]["url"])
        first_call_args = ddg_mock.await_args_list[0].kwargs
        first_queries = ddg_mock.await_args_list[0].args[0]
        self.assertEqual(first_queries[0], "Kindle Paperwhite vs Kobo Clara")
        self.assertIn("site:the-ebook-reader.com Kindle Paperwhite vs Kobo Clara", first_queries)
        self.assertEqual(first_call_args["timeout_s"], 7.0)

    async def test_comparison_group_matching_rejects_adjacent_models(self) -> None:
        handler = WebSearchHandler()
        blob = "Dell XPS 14 vs MacBook Pro 14-inch comparison with benchmarks and pricing."
        self.assertEqual(handler._comparison_group_hit_count("pros and cons of MacBook Air vs Dell XPS 13", blob), 0)

    async def test_shopping_row_filter_rejects_variant_drift_for_plain_family_compare(self) -> None:
        handler = WebSearchHandler()
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "pros and cons of MacBook Air vs Dell XPS 13",
                {
                    "title": "Dell XPS 13 Plus (2022) vs Apple MacBook Air 13 (M2, 2022)",
                    "url": "https://www.rtings.com/laptop/tools/compare/dell-xps-13-plus-2022-vs-apple-macbook-air-13-m2-2022/31397/33915",
                    "description": "Comparison of Dell XPS 13 Plus and MacBook Air.",
                },
            )
        )

    async def test_shopping_row_filter_rejects_ereader_third_device_and_variant_drift(self) -> None:
        handler = WebSearchHandler()
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Kindle Paperwhite vs. Kobo Clara and Boox Poke: Which E-Reader Should You Buy?",
                    "url": "https://www.techtimes.com/articles/e-readers.htm",
                    "description": "Compare Kindle Paperwhite vs Kobo Clara and Boox Poke to find the best e-reader.",
                },
            )
        )
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Kindle Paperwhite vs Kobo Clara 2E",
                    "url": "https://example.com/kindle-vs-kobo-clara-2e",
                    "description": "Travel e-reader comparison.",
                },
            )
        )

    async def test_shopping_row_filter_allows_current_kobo_clara_family_variants_for_generic_ereader_compare(self) -> None:
        handler = WebSearchHandler()
        self.assertFalse(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Kindle Paperwhite vs Kobo Clara BW: Which eReader is better?",
                    "url": "https://www.today.com/shop/kindle-paperwhite-vs-kobo-clara-bw-rcna200008",
                    "description": "Comparison of Kindle Paperwhite and Kobo Clara BW.",
                },
            )
        )
        self.assertFalse(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Kindle Paperwhite vs Kobo Clara Colour review | Mashable",
                    "url": "https://mashable.com/comparison/kindle-paperwhite-vs-kobo-clara-colour-review",
                    "description": "Comparison review for Kindle Paperwhite and Kobo Clara Colour.",
                },
            )
        )

    async def test_shopping_row_filter_rejects_ereader_pinterest_and_cdn_mirror_rows(self) -> None:
        handler = WebSearchHandler()
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "New Kindle Paperwhite Vs Kobo Clara Colour: Which EReader Is The Best ...",
                    "url": "https://www.pinterest.com/pin/new-kindle-paperwhite-vs-kobo-clara-colour-which-ereader-is-the-best-buy--767089749069521171/",
                    "description": "Pinned comparison roundup.",
                },
            )
        )
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Amazon Kindle Paperwhite vs Kobo Clara HD: What is the difference?",
                    "url": "https://d2kb8322hvxqt8.cloudfront.net/en/amazon-kindle-paperwhite-vs-kobo-clara-hd",
                    "description": "Mirror of a comparison page.",
                },
            )
        )

    async def test_shopping_compare_retry_hosts_use_ereader_trusted_sites(self) -> None:
        handler = WebSearchHandler()
        hosts = handler._shopping_compare_retry_hosts("which is better Kindle Paperwhite or Kobo Clara")
        self.assertIn("the-ebook-reader.com", hosts)
        self.assertIn("tomsguide.com", hosts)

    async def test_shopping_compare_retry_hosts_use_console_and_printer_trusted_sites(self) -> None:
        handler = WebSearchHandler()
        console_hosts = handler._shopping_compare_retry_hosts("should I buy PlayStation 5 or Xbox Series X")
        printer_hosts = handler._shopping_compare_retry_hosts("which is better Brother laser printer or HP LaserJet")
        self.assertIn("ign.com", console_hosts)
        self.assertIn("gamesradar.com", console_hosts)
        self.assertIn("rtings.com", printer_hosts)
        self.assertIn("wirecutter.com", printer_hosts)

    async def test_comparison_group_hit_count_accepts_console_aliases(self) -> None:
        handler = WebSearchHandler()
        blob = "PS5 vs Xbox Series X: which console should you buy in 2026"
        self.assertEqual(handler._comparison_group_hit_count("should I buy PlayStation 5 or Xbox Series X", blob), 2)

    async def test_shopping_compare_signal_requires_both_requested_subjects_for_pair_query(self) -> None:
        handler = WebSearchHandler()
        self.assertFalse(
            handler._shopping_row_has_direct_compare_signal(
                "which is better Kindle Paperwhite or Kobo Clara",
                {
                    "title": "Kindle Paperwhite vs Kindle Comparison Review - 2024 Edition",
                    "url": "https://blog.the-ebook-reader.com/2024/10/25/kindle-paperwhite-vs-kindle-comparison-review/",
                    "description": "Updated comparison review between the new Kindle models.",
                },
            )
        )

    async def test_ereader_compare_scoring_prefers_trusted_review_hosts_over_content_farms(self) -> None:
        handler = WebSearchHandler()
        trusted_row = {
            "title": "Kindle Paperwhite vs Kobo Clara Colour: Which is the better e-reader?",
            "url": "https://www.tomsguide.com/versus/kindle-paperwhite-vs-kobo-clara-colour",
            "description": "Compare the Kindle Paperwhite and Kobo Clara across display, battery life, and ecosystem.",
        }
        noisy_row = {
            "title": "Kindle Paperwhite vs Kobo Clara. The Best e-Readers",
            "url": "https://www.bookrunch.org/kindle-paperwhite-vs-kobo-clara",
            "description": "Kindle Paperwhite vs Kobo Clara in our news archive and roundup.",
        }
        self.assertGreater(
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", trusted_row),
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", noisy_row),
        )
        versus_row = {
            "title": "Amazon Kindle Paperwhite vs Kobo Clara Colour: What is the difference?",
            "url": "https://versus.com/en/amazon-kindle-paperwhite-vs-kobo-clara-colour",
            "description": "Spec comparison page.",
        }
        self.assertGreater(
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", trusted_row),
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", versus_row),
        )
        video_row = {
            "title": "Kindle Paperwhite vs Kobo Clara HD Comparison (Video)",
            "url": "https://blog.the-ebook-reader.com/2018/06/12/kindle-paperwhite-vs-kobo-clara-hd-comparison-video/",
            "description": "Video comparison between Kindle Paperwhite and Kobo Clara.",
        }
        self.assertGreater(
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", trusted_row),
            handler._score_browse_row("which is better Kindle Paperwhite or Kobo Clara", video_row),
        )
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "pros and cons of MacBook Air vs Dell XPS 13",
                {
                    "title": "Dell XPS 14 (2026) vs. MacBook Pro 14-inch M5: Which laptop wins?",
                    "url": "https://www.tomsguide.com/computing/laptops/dell-xps-14-2026-vs-macbook-pro-14-inch-m5-which-laptop-wins",
                    "description": "Comparison of Dell XPS 14 and MacBook Pro 14-inch.",
                },
            )
        )
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "pros and cons of MacBook Air vs Dell XPS 13",
                {
                    "title": "Dell XPS 13 vs. MacBook Air 13",
                    "url": "https://gadgetsalvation.medium.com/dell-xps-13-vs-macbook-air-13-9fdf54215fd1",
                    "description": "Medium comparison post.",
                },
            )
        )

    async def test_shopping_compare_row_filter_rejects_single_product_reviews_with_incidental_mentions(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "pros and cons of MacBook Air vs Dell XPS 13",
            {
                "title": "Dell XPS 13 9350 laptop review: Intel Lunar Lake is the perfect fit",
                "url": "https://www.notebookcheck.net/Dell-XPS-13-9350-laptop-review-Intel-Lunar-Lake-is-the-perfect-fit.911314.0.html",
                "description": "The changes help make the XPS 13 an even better contender to the MacBook Air 13 series.",
            },
        )
        self.assertFalse(allowed)

    async def test_shopping_row_filter_rejects_affiliate_compare_pages_after_content_fetch(self) -> None:
        handler = WebSearchHandler()
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "pros and cons of MacBook Air vs Dell XPS 13",
                {
                    "title": "Dell XPS 13 vs MacBook Air: Which Ultraportable Reigns?",
                    "url": "https://versusguy.com/dell-xps-13-vs-macbook-air/",
                    "description": "Head-to-head comparison of Dell XPS 13 and MacBook Air.",
                    "content": "Disclosure: As an Amazon Associate, I earn from qualifying purchases. This post may contain affiliate links, which means I may receive a small commission at no extra cost to you.",
                },
            )
        )

    async def test_shopping_compare_signal_rejects_generic_comparison_hub_without_requested_pair(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._shopping_row_has_direct_compare_signal(
            "difference between MacBook Air and Dell XPS 13",
            {
                "title": "Laptop Comparison by Specs & Tests",
                "url": "https://nanoreview.net/en/laptop-compare",
                "description": "Compare laptops head-to-head by battery life, value, and display quality.",
            },
        )
        self.assertFalse(allowed)

    async def test_shopping_row_filter_rejects_mojibake_or_foreign_noise_for_english_query(self) -> None:
        handler = WebSearchHandler()
        self.assertTrue(
            handler._shopping_row_looks_noisy(
                "which is better iPhone 16 or Samsung Galaxy S25",
                {
                    "title": "????????? Samsung Galaxy S25 ? Apple iPhone 16: ??? ??????",
                    "url": "https://nanoreview.net/en/phone-compare/samsung-galaxy-s25-vs-apple-iphone-16",
                    "description": "?????? ????? ?? ??? ??????? ? 2025 ????",
                },
            )
        )

    async def test_search_web_uses_shopping_compare_fast_path_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="compare iPhone 16 and Samsung Galaxy S25",
            query_variants=["iPhone 16 vs Samsung Galaxy S25", "iPhone 16 Samsung Galaxy S25 comparison"],
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Compare Apple iPhone 16 vs. Samsung Galaxy S25 - GSMArena.com",
                "url": "https://www.gsmarena.com/compare.php3?idPhone1=13317&idPhone2=13610",
                "description": "Detailed specs comparison for the Samsung Galaxy S25 and Apple iPhone 16.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_shopping_compare_browse", AsyncMock(return_value=fake_rows)) as compare_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("compare iPhone 16 and Samsung Galaxy S25")
        compare_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertIn("gsmarena.com", rows[0]["url"])

    async def test_search_web_skips_generic_deep_browse_when_shopping_fast_path_is_empty(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="should I buy Kindle Paperwhite or Kobo Clara",
            query_variants=["Kindle Paperwhite vs Kobo Clara"],
            reason="freshness_or_depth_needed",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_shopping_compare_browse", AsyncMock(return_value=[])) as compare_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[{"title": "should not run"}])) as deep_mock:
                    rows = await handler.search_web("should I buy Kindle Paperwhite or Kobo Clara")
        compare_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertEqual(rows, [])

    async def test_shopping_compare_browse_uses_searx_fallback_when_ddg_is_empty(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="which is better Brother laser printer or HP LaserJet",
            query_variants=["Brother laser printer vs HP LaserJet", "Brother vs HP LaserJet review"],
            reason="freshness_or_depth_needed",
        )
        searx_rows = [
            {
                "title": "Brother MFC-L3770CDW Laser vs HP Color LaserJet Pro MFP M479fdw",
                "url": "https://www.rtings.com/printer/tools/compare/brother-mfc-l3770cdw-laser-vs-hp-color-laserjet-pro-mfp-m479fdw/7156/10222",
                "description": "Detailed laser printer comparison.",
                "source": "searxng_general",
            }
        ]
        with patch.object(handler, "_variant_ddg_rows", AsyncMock(side_effect=[[], []])) as ddg_mock:
            with patch.object(handler, "_variant_searx_rows", AsyncMock(return_value=searx_rows)) as searx_mock:
                with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=searx_rows)) as fetch_mock:
                    rows = await handler._shopping_compare_browse("which is better Brother laser printer or HP LaserJet", plan)
        self.assertGreaterEqual(ddg_mock.await_count, 1)
        searx_mock.assert_awaited_once()
        fetch_mock.assert_awaited_once()
        self.assertIn("rtings.com", rows[0]["url"])
        self.assertTrue(any("SearXNG added" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_shopping_compare_browse_uses_search_general_rescue_after_empty_ddg_and_searx(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="should I buy PlayStation 5 or Xbox Series X",
            query_variants=["PlayStation 5 vs Xbox Series X", "should I buy PlayStation 5 or Xbox Series X"],
            reason="freshness_or_depth_needed",
        )
        rescued_rows = [
            {
                "title": "PS5 vs Xbox Series X: Which Console Wins?",
                "url": "https://www.techradar.com/gaming/consoles/ps5-vs-xbox-series-x",
                "description": "A focused console comparison.",
                "source": "search_general",
            }
        ]
        with patch.object(handler, "_variant_ddg_rows", AsyncMock(side_effect=[[], []])) as ddg_mock:
            with patch.object(handler, "_variant_searx_rows", AsyncMock(return_value=[])) as searx_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=rescued_rows)) as general_mock:
                    with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=rescued_rows)) as fetch_mock:
                        rows = await handler._shopping_compare_browse("should I buy PlayStation 5 or Xbox Series X", plan)
        self.assertGreaterEqual(ddg_mock.await_count, 1)
        searx_mock.assert_awaited_once()
        self.assertGreaterEqual(general_mock.await_count, 1)
        fetch_mock.assert_awaited_once()
        self.assertIn("techradar.com", rows[0]["url"])
        self.assertTrue(any("search-general rescue added" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_search_web_uses_software_change_fast_path_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest fastapi release notes",
            query_variants=["latest fastapi release notes", "fastapi release notes"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Release Notes - FastAPI",
                "url": "https://fastapi.tiangolo.com/release-notes/",
                "description": "Official FastAPI release notes.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_software_change_browse", AsyncMock(return_value=fake_rows)) as software_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("latest fastapi release notes")
        software_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertIn("fastapi.tiangolo.com", rows[0]["url"])

    async def test_search_web_quick_mode_recovers_with_searx_after_ddg_timeout(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="quick",
            query="how many calories to lose weight",
            query_variants=["how many calories to lose weight"],
            reason="simple_lookup",
        )
        searx_rows = [
            {
                "title": "How Many Calories Should I Eat to Lose Weight?",
                "url": "https://www.healthline.com/nutrition/how-many-calories-per-day",
                "description": "A practical calorie estimate and explanation.",
                "source": "searxng_general",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_ddg_text", AsyncMock(side_effect=asyncio.TimeoutError)) as ddg_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.search_searxng", AsyncMock(return_value=searx_rows)) as searx_mock:
                    rows = await handler.search_web("how many calories to lose weight")
        ddg_mock.assert_awaited_once()
        searx_mock.assert_awaited_once()
        self.assertEqual(rows[0]["url"], "https://www.healthline.com/nutrition/how-many-calories-per-day")
        self.assertTrue(any("recovered" in step.lower() and "searxng" in step.lower() for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_search_web_quick_mode_uses_single_bounded_attempt_when_recovery_is_empty(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="quick",
            query="how many calories to lose weight",
            query_variants=["how many calories to lose weight"],
            reason="simple_lookup",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_ddg_text", AsyncMock(side_effect=asyncio.TimeoutError)) as ddg_mock:
                with patch("workshop.toolbox.stacks.web_core.websearch.search_searxng", AsyncMock(return_value=[])) as searx_mock:
                    rows = await handler.search_web("how many calories to lose weight")
        ddg_mock.assert_awaited_once()
        searx_mock.assert_awaited_once()
        self.assertEqual(rows, [])

    async def test_search_web_uses_official_fast_path_before_deep_browse(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest passport renewal requirements",
            query_variants=["site:travel.state.gov latest passport renewal requirements", "latest passport renewal requirements"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        fake_rows = [
            {
                "title": "Renew Your Passport by Mail - Travel",
                "url": "https://travel.state.gov/content/travel/en/passports/have-passport/renew.html",
                "description": "Official passport renewal requirements.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=plan):
            with patch.object(handler, "_official_preferred_browse", AsyncMock(return_value=fake_rows)) as official_mock:
                with patch.object(handler, "_deep_browse", AsyncMock(return_value=[])) as deep_mock:
                    rows = await handler.search_web("latest passport renewal requirements")
        official_mock.assert_awaited_once()
        deep_mock.assert_not_called()
        self.assertIn("travel.state.gov", rows[0]["url"])

    async def test_trip_planning_fast_path_returns_shortlist_without_research_compose(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="plan a 3 day trip to Tokyo",
            query_variants=["3 day Tokyo itinerary", "Tokyo itinerary 3 days"],
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "Tokyo Itineraries - Japan-Guide",
                "url": "https://www.japan-guide.com/e/e3051_tokyo.html",
                "description": "Suggested itineraries for spending 1-5 days in Tokyo.",
            },
            {
                "title": "3 Days in Tokyo: The Perfect First-Timer's Itinerary",
                "url": "https://www.lonelyplanet.com/articles/3-days-in-tokyo",
                "description": "A first-time Tokyo itinerary with food stops and neighborhoods.",
            },
            {
                "title": "Tokyo Itinerary 3 Days",
                "url": "https://www.timeout.com/tokyo/things-to-do/tokyo-itinerary-3-days",
                "description": "Three days in Tokyo with things to do each day.",
            },
        ]
        with patch.object(handler, "_ddg_text", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                rows = await handler._trip_planning_browse("plan a 3 day trip to Tokyo", plan)
        self.assertGreaterEqual(search_mock.await_count, 1)
        fetch_mock.assert_awaited_once()
        self.assertIn("japan-guide.com", rows[0]["url"])
        self.assertTrue(any("travel fast path looked sufficient" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_trip_planning_fast_path_uses_bounded_ddg_search(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="budget for 4 days in Seoul",
            query_variants=["budget for 4 days in Seoul", "Seoul itinerary"],
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "4 Days in Seoul Budget Itinerary",
                "url": "https://example.com/seoul-budget",
                "description": "A four-day Seoul itinerary with budget tips and daily costs.",
            }
        ]
        with patch.object(handler, "_ddg_text", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)):
                rows = await handler._trip_planning_browse("budget for 4 days in Seoul", plan)
        self.assertTrue(rows)
        self.assertGreaterEqual(search_mock.await_count, 1)

    async def test_trip_planning_prioritization_prefers_itinerary_guide_over_tripadvisor_article(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "plan a 3 day trip to Tokyo",
            [
                {
                    "title": "3 days in Tokyo: The perfect itinerary - Tripadvisor",
                    "url": "https://www.tripadvisor.com/Articles-l7e4rcYGvA6c-3_days_in_tokyo.html",
                    "description": "A high-level Tokyo itinerary article.",
                },
                {
                    "title": "Tokyo itineraries - Japan-Guide",
                    "url": "https://www.japan-guide.com/e/e3051_tokyo.html",
                    "description": "Suggested itineraries for spending 1-5 days in Tokyo.",
                },
            ],
        )
        self.assertIn("japan-guide.com", rows[0]["url"])

    async def test_travel_lookup_fast_path_returns_shortlist_without_research_compose(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="best time to visit Tokyo",
            query_variants=["best time to visit Tokyo", "Tokyo weather seasons", "when to visit Tokyo"],
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "Best Time to Visit Tokyo | Japan-Guide",
                "url": "https://www.japan-guide.com/e/e2273.html",
                "description": "Advice on the best seasons and months to visit Tokyo.",
            },
            {
                "title": "Best Time to Visit Tokyo (2026) - Condé Nast Traveler",
                "url": "https://www.cntraveler.com/story/best-time-to-visit-tokyo",
                "description": "A seasonal breakdown of weather, crowds, and events in Tokyo.",
            },
            {
                "title": "Tokyo weather seasons | Go Tokyo",
                "url": "https://www.gotokyo.org/en/plan/when-to-visit/index.html",
                "description": "Official tourism guidance on Tokyo's seasons and best times to visit.",
            },
        ]
        with patch.object(handler, "_ddg_text", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_variant_searx_rows", AsyncMock(return_value=[])):
                with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                    rows = await handler._travel_lookup_browse("best time to visit Tokyo", plan)
        self.assertGreaterEqual(search_mock.await_count, 1)
        fetch_mock.assert_awaited_once()
        self.assertTrue(any(domain in rows[0]["url"] for domain in ("japan-guide.com", "gotokyo.org")))
        self.assertTrue(any("travel lookup fast path looked sufficient" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_travel_enrichment_candidates_skip_slow_usnews_host(self) -> None:
        handler = WebSearchHandler()
        rows = [
            {
                "title": "Top Things to Do in Paris | U.S. News Travel",
                "url": "https://travel.usnews.com/Paris_France/Things_To_Do/",
                "description": "U.S. News things to do guide for Paris.",
            },
            {
                "title": "The 22 best things to do in Paris - Conde Nast Traveler",
                "url": "https://www.cntraveler.com/gallery/best-things-to-do-in-paris",
                "description": "Traveler guide to the best things to do in Paris.",
            },
        ]
        candidates = handler._travel_enrichment_candidates("what to do in Paris", rows, limit=1)
        self.assertEqual(len(candidates), 1)
        self.assertIn("cntraveler.com", candidates[0]["url"])

    async def test_travel_lookup_prioritization_demotes_ranking_pages_for_things_to_do_queries(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "top things to do in Tokyo",
            [
                {
                    "title": "RANKING | The Official Tokyo Travel Guide, GO TOKYO",
                    "url": "https://www.gotokyo.org/en/see-and-do/ranking/index.html",
                    "description": "Ranking page of Tokyo activities.",
                },
                {
                    "title": "Visit Tokyo - The Official Travel Guide of Tokyo, GO TOKYO",
                    "url": "https://www.gotokyo.org/en/",
                    "description": "Official Tokyo travel guide for visitors.",
                },
            ],
            prefer_official=False,
        )
        self.assertIn("Visit Tokyo", rows[0]["title"])

    async def test_shopping_compare_fast_path_returns_shortlist_without_research_compose(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="compare iPhone 16 and Samsung Galaxy S25",
            query_variants=["iPhone 16 vs Samsung Galaxy S25", "iPhone 16 Samsung Galaxy S25 comparison"],
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "Compare Apple iPhone 16 vs. Samsung Galaxy S25 - GSMArena.com",
                "url": "https://www.gsmarena.com/compare.php3?idPhone1=13317&idPhone2=13610",
                "description": "Detailed specs comparison for the Samsung Galaxy S25 and Apple iPhone 16.",
            },
            {
                "title": "iPhone 16 vs Samsung Galaxy S25: Which is better? | TechRadar",
                "url": "https://www.techradar.com/phones/iphone-16-vs-samsung-galaxy-s25",
                "description": "Comparison of cameras, battery life, display, and value.",
            },
        ]
        with patch.object(handler, "_ddg_text", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                rows = await handler._shopping_compare_browse("compare iPhone 16 and Samsung Galaxy S25", plan)
        self.assertGreaterEqual(search_mock.await_count, 1)
        fetch_mock.assert_awaited_once()
        self.assertIn("gsmarena.com", rows[0]["url"])
        self.assertTrue(any("shopping fast path looked sufficient" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_software_change_fast_path_returns_shortlist_without_research_compose(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest fastapi release notes",
            query_variants=["latest fastapi release notes", "fastapi release notes"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "Release Notes - FastAPI",
                "url": "https://fastapi.tiangolo.com/release-notes/",
                "description": "Latest changes and release notes for FastAPI.",
            },
            {
                "title": "Releases - fastapi/fastapi - GitHub",
                "url": "https://github.com/fastapi/fastapi/releases",
                "description": "GitHub releases for FastAPI.",
            },
        ]
        with patch.object(handler, "_ddg_text", AsyncMock(return_value=raw_rows)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                rows = await handler._software_change_browse("latest fastapi release notes", plan)
        self.assertGreaterEqual(search_mock.await_count, 1)
        fetch_mock.assert_awaited_once()
        self.assertIn("fastapi.tiangolo.com", rows[0]["url"])
        self.assertTrue(any("software-change fast path" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_software_change_fast_path_uses_direct_typescript_adapter_before_ddg(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="what changed in typescript 5.8 docs",
            query_variants=["what changed in typescript 5.8 docs", "typescript 5.8 release notes"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        direct_rows = [
            {
                "title": "TypeScript 5.8 release notes",
                "url": "https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html",
                "description": "Official TypeScript 5.8 release notes and documentation changes.",
                "content": "TypeScript 5.8 release notes.",
            }
        ]
        with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=direct_rows)) as fetch_mock:
            with patch.object(handler, "_variant_ddg_rows", AsyncMock(return_value=[])) as ddg_mock:
                rows = await handler._software_change_browse("what changed in typescript 5.8 docs", plan)
        fetch_mock.assert_awaited_once()
        ddg_mock.assert_not_awaited()
        self.assertEqual(rows[0]["url"], "https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html")
        self.assertTrue(any("direct software release adapter" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_official_fast_path_returns_official_shortlist_without_deep_search(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest passport renewal requirements",
            query_variants=["site:travel.state.gov latest passport renewal requirements", "latest passport renewal requirements"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "Renew Your Passport by Mail - Travel",
                "url": "https://travel.state.gov/content/travel/en/passports/have-passport/renew.html",
                "description": "Official passport renewal requirements for U.S. passports.",
            },
            {
                "title": "Renew an adult passport - USAGov",
                "url": "https://www.usa.gov/renew-adult-passport",
                "description": "Official renewal overview.",
            },
        ]
        with patch.object(handler, "_known_official_seed_rows", return_value=[]):
            with patch.object(handler, "_variant_searx_rows", AsyncMock(return_value=raw_rows)) as search_mock:
                with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)) as fetch_mock:
                    rows = await handler._official_preferred_browse("latest passport renewal requirements", plan)
        search_mock.assert_awaited_once()
        fetch_mock.assert_awaited_once()
        self.assertIn("travel.state.gov", rows[0]["url"])
        self.assertTrue(any("official-source fast path" in step for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_official_fast_path_can_use_known_fafsa_seed_without_search(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="current FAFSA deadlines",
            query_variants=["current FAFSA deadlines", "site:studentaid.gov current FAFSA deadlines"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        with patch.object(handler, "_variant_searx_rows", AsyncMock(return_value=[])) as searx_mock:
            rows = await handler._official_preferred_browse("current FAFSA deadlines", plan)
        searx_mock.assert_not_awaited()
        self.assertIn("studentaid.gov", rows[0]["url"])
        self.assertTrue(any("known official page adapter" in step.lower() for step in list((handler.last_browse_report or {}).get("execution_steps") or [])))

    async def test_summarize_result_rows_flags_page_source_mash_as_bad_text(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "compare iPhone 16 and Samsung Galaxy S25",
            [
                {
                    "title": "Apple iPhone 16 vs Samsung Galaxy S25 - specs comparison - PhoneArena",
                    "url": "https://www.phonearena.com/phones/compare/Apple-iPhone-16,Samsung-Galaxy-S25/phones/12240,12340",
                    "description": "*{box-sizing:border-box} body{display:flex} @font-face{src:url(fake.woff2)} window['cfg']={a:1}",
                },
                {
                    "title": "Compare Samsung Galaxy S25 vs. Apple iPhone 16 - GSMArena.com",
                    "url": "https://www.gsmarena.com/compare.php3?idPhone1=13610&idPhone2=13317",
                    "description": "Detailed specs comparison for the Samsung Galaxy S25 and Apple iPhone 16.",
                },
            ],
        )
        self.assertTrue(summary.startswith("Apple iPhone 16 vs Samsung Galaxy S25"))
        self.assertNotIn("box-sizing", summary)

    async def test_summarize_result_rows_falls_back_when_excerpt_starts_mid_sentence(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "plan a 3 day trip to Tokyo",
            [
                {
                    "title": "3 days in Tokyo: The perfect itinerary - Tripadvisor",
                    "url": "https://www.tripadvisor.com/Articles-lEkRqRI5iHOA-3_days_in_tokyo_itinerary.html",
                    "description": "...aplantosee the fabulous fashions of Ginza and the colorful anime of Akihabara in three days.",
                },
                {
                    "title": "Tokyo 3-Day Itinerary: Traveling to Tokyo for the First Time",
                    "url": "https://www.nextleveloftravel.com/japan/tokyo-3-day-itinerary/",
                    "description": "A first-timer Tokyo itinerary with neighborhoods, food, and transit tips.",
                },
            ],
        )
        self.assertTrue(summary.startswith("3 days in Tokyo: The perfect itinerary"))
        self.assertNotIn("...aplantosee", summary)

    async def test_summarize_result_rows_falls_back_when_excerpt_is_short_ellipsis(self) -> None:
        handler = WebSearchHandler()
        summary = handler._summarize_result_rows(
            "plan a 3 day trip to Tokyo",
            [
                {
                    "title": "Perfect 3 Days in Tokyo (2026): The Ultimate Itinerary for First-Time Visitors",
                    "url": "https://tokyocandies.com/3-days-in-tokyo-itinerary/",
                    "description": "Planning ...",
                },
                {
                    "title": "How to Plan a Perfect 3-Day Itinerary in Tokyo (2026)",
                    "url": "https://www.japanhighlights.com/japan/tokyo/3-day-itinerary",
                    "description": "A practical Tokyo itinerary for first-time visitors.",
                },
            ],
        )
        self.assertTrue(summary.startswith("Perfect 3 Days in Tokyo"))
        self.assertNotIn("Planning ...", summary)

    async def test_deep_browse_uses_general_domain_for_official_fallback(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest ACC/AHA hypertension guideline",
            query_variants=["latest ACC/AHA hypertension guideline", "site:acc.org latest ACC/AHA hypertension guideline"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        class _Bundle:
            def __init__(self) -> None:
                self.items = []
                self.claims = []
                self.conflicts = []
                self.limitations = []

            def as_dict(self):
                return {"items": []}

        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=[])):
            with patch("workshop.toolbox.stacks.web_core.websearch.research_compose", AsyncMock(return_value=_Bundle())) as compose_mock:
                await handler._deep_browse("latest ACC/AHA hypertension guideline", plan)
        self.assertEqual(compose_mock.await_args.kwargs.get("domain_override"), "general")

    async def test_deep_browse_shopping_compare_prefers_row_summary(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="compare iPhone 16 and Samsung Galaxy S25",
            query_variants=["iPhone 16 vs Samsung Galaxy S25"],
            reason="freshness_or_depth_needed",
        )

        class _Bundle:
            def __init__(self) -> None:
                self.items = []
                self.claims = []
                self.conflicts = []
                self.limitations = []
                self.queries = []
                self.answer = ""

            def as_dict(self):
                return {"items": []}

        rows_from_bundle = [
            {
                "title": "Compare Apple iPhone 16 vs. Samsung Galaxy S25 - GSMArena.com",
                "url": "https://www.gsmarena.com/compare.php3?idPhone1=13317&idPhone2=13610",
                "description": "Detailed specs comparison for the Samsung Galaxy S25 and Apple iPhone 16.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.research_compose", AsyncMock(return_value=_Bundle())):
            with patch.object(handler, "_rows_from_evidence_bundle", return_value=rows_from_bundle):
                with patch.object(handler, "_summarize_result_rows", return_value="Clean compare summary") as row_summary_mock:
                    with patch.object(handler, "_summarize_evidence_bundle", return_value="Noisy claim bundle") as bundle_summary_mock:
                        await handler._deep_browse("compare iPhone 16 and Samsung Galaxy S25", plan)
        row_summary_mock.assert_called_once()
        bundle_summary_mock.assert_not_called()
        self.assertEqual((handler.last_browse_report or {}).get("summary"), "Clean compare summary")

    async def test_deep_browse_keeps_official_shortlist_when_research_fallback_is_noisy(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest WHO dengue treatment guidance",
            query_variants=[
                "site:who.int 2025 arboviral diseases dengue guideline",
                "latest WHO dengue treatment guidance",
            ],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )

        class _Bundle:
            def __init__(self) -> None:
                self.items = []
                self.claims = []
                self.conflicts = []
                self.limitations = []
                self.queries = []
                self.answer = ""

            def as_dict(self):
                return {"items": []}

        official_rows = [
            {
                "title": "New WHO guidelines for clinical management of arboviral diseases",
                "url": "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                "description": "2025 WHO arboviral diseases guideline update.",
            }
        ]
        noisy_research_rows = [
            {
                "title": "Dengue guidelines, for diagnosis, treatment, prevention and control",
                "url": "https://www.who.int/publications/m/item/dengue-guidelines-for-diagnosis-treatment-prevention-and-control",
                "description": "Older WHO dengue page.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=official_rows)):
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=official_rows)):
                with patch.object(handler, "_official_rows_adequate", return_value=False):
                    with patch("workshop.toolbox.stacks.web_core.websearch.research_compose", AsyncMock(return_value=_Bundle())):
                        with patch.object(handler, "_rows_from_evidence_bundle", return_value=noisy_research_rows):
                            rows = await handler._deep_browse("latest WHO dengue treatment guidance", plan)
        self.assertIn("/news/item/", rows[0]["url"])
        self.assertTrue(any("who.int/news/item" in str((row or {}).get("url") or "") for row in rows[:2]))

    async def test_deep_browse_tries_more_who_site_variants_before_stopping(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest WHO dengue treatment guidance",
            query_variants=[
                "site:who.int 2025 arboviral diseases dengue guideline",
                "site:who.int 2025 dengue clinical management guideline",
                "site:who.int new WHO guidelines clinical management arboviral diseases dengue",
                'site:who.int "new WHO guidelines for clinical management of arboviral diseases" dengue',
                "latest WHO dengue treatment guidance",
            ],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        search_results = {
            "site:who.int 2025 arboviral diseases dengue guideline": [],
            "site:who.int 2025 dengue clinical management guideline": [
                {
                    "title": "National Guideline for Clinical Management of Dengue 2022",
                    "url": "https://www.who.int/timorleste/publications/national-guideline-for-clinical-management-of-dengue-2022",
                    "description": "Timor-Leste country guidance page.",
                }
            ],
            "site:who.int new WHO guidelines clinical management arboviral diseases dengue": [
                {
                    "title": "New WHO guidelines for clinical management of arboviral diseases",
                    "url": "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    "description": "2025 WHO arboviral diseases guideline update.",
                },
                {
                    "title": "WHO guidelines for clinical management of arboviral diseases",
                    "url": "https://www.who.int/publications/i/item/9789240111110",
                    "description": "WHO publication page for the 2025 arboviral guideline.",
                },
            ],
        }

        async def _fake_search(query: str, min_results: int = 3, budgets_ms=None, allow_ddg_fallback: bool = True):
            return list(search_results.get(query, []))

        async def _passthrough(rows, category="general", top_n=2, max_n=6):
            return list(rows or [])

        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(side_effect=_fake_search)) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(side_effect=_passthrough)):
                with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                    rows = await handler._deep_browse("latest WHO dengue treatment guidance", plan)
        awaited_queries = [str(item.args[0]) for item in list(search_mock.await_args_list or [])]
        self.assertEqual(
            awaited_queries,
            [
                "site:who.int 2025 arboviral diseases dengue guideline",
                "site:who.int 2025 dengue clinical management guideline",
                "site:who.int new WHO guidelines clinical management arboviral diseases dengue",
            ],
        )
        self.assertIn("/news/item/", rows[0]["url"])

    async def test_deep_browse_falls_back_to_agentpedia_memory_when_live_research_is_empty(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="what changed in python 3.13 docs",
            query_variants=["what changed in python 3.13 docs", "site:docs.python.org What's New In Python 3.13"],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )

        class _Bundle:
            def __init__(self) -> None:
                self.items = []
                self.claims = []
                self.conflicts = []
                self.limitations = []
                self.queries = []
                self.answer = ""

            def as_dict(self):
                return {"items": []}

        memory_rows = [
            {
                "title": "What's New In Python 3.13",
                "url": "https://docs.python.org/3/whatsnew/3.13.html",
                "description": "Python 3.13 adds a new REPL, free-threaded mode, and other standard library changes.",
                "source": "agentpedia_kb",
            }
        ]
        with patch.object(handler, "_agentpedia_memory_rows", return_value=memory_rows):
            with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=[])):
                    with patch("workshop.toolbox.stacks.web_core.websearch.research_compose", AsyncMock(return_value=_Bundle())):
                        rows = await handler._deep_browse("what changed in python 3.13 docs", plan)
        self.assertEqual(rows[0]["url"], "https://docs.python.org/3/whatsnew/3.13.html")
        steps = list((handler.last_browse_report or {}).get("execution_steps") or [])
        self.assertTrue(any("falling back to 1 Agentpedia row" in step for step in steps))

    async def test_deep_browse_writes_agentpedia_memory_after_successful_official_pass(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="latest ACC/AHA hypertension guideline",
            query_variants=["latest ACC/AHA hypertension guideline", "site:acc.org latest ACC/AHA hypertension guideline"],
            needs_recency=True,
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        raw_rows = [
            {
                "title": "2025 High Blood Pressure Guidelines",
                "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                "description": "Official guideline page.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=raw_rows)):
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=raw_rows)):
                with patch.object(handler, "_write_agentpedia_memory", return_value=2) as write_mock:
                    rows = await handler._deep_browse("latest ACC/AHA hypertension guideline", plan)
        write_mock.assert_called_once()
        self.assertIn("ahajournals.org", rows[0]["url"])
        steps = list((handler.last_browse_report or {}).get("execution_steps") or [])
        self.assertTrue(any("persisted 2 Agentpedia fact row(s) from official browse" in step for step in steps))

    async def test_deep_browse_python_docs_continues_until_docs_page_is_found(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="deep",
            query="what changed in python 3.13 docs",
            query_variants=[
                "what changed in python 3.13 docs",
                "site:docs.python.org What's New In Python 3.13",
                "site:python.org Python 3.13 release",
            ],
            official_preferred=True,
            reason="freshness_or_depth_needed",
        )
        release_rows = [
            {
                "title": "Python Release Python 3.13.0a4 | Python.org",
                "url": "https://www.python.org/downloads/release/python-3130a4/",
                "description": "Alpha release preview page.",
            }
        ]
        docs_rows = [
            {
                "title": "What's New In Python 3.13",
                "url": "https://docs.python.org/3/whatsnew/3.13.html",
                "description": "Python 3.13 documentation release highlights.",
            }
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(side_effect=[release_rows, docs_rows])) as search_mock:
            with patch.object(handler, "_fetch_and_attach_content", AsyncMock(return_value=docs_rows)):
                with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                    rows = await handler._deep_browse("what changed in python 3.13 docs", plan)
        self.assertGreaterEqual(search_mock.await_count, 2)
        self.assertEqual(rows[0]["url"], "https://docs.python.org/3/whatsnew/3.13.html")

    async def test_github_browse_falls_back_to_agentpedia_when_no_repo_is_verified(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="check out openclaw on github",
            query_variants=["site:github.com openclaw"],
            reason="github_lookup",
        )
        memory_rows = [
            {
                "title": "openclaw/openclaw on GitHub",
                "url": "https://github.com/openclaw/openclaw",
                "description": "OpenClaw is a GitHub repository.",
                "source": "agentpedia_kb",
            }
        ]
        with patch.object(handler, "_agentpedia_memory_rows", return_value=memory_rows):
            with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=[])):
                with patch("workshop.toolbox.stacks.web_core.websearch.choose_repositories", return_value=[]):
                    rows = await handler._github_browse("check out openclaw on github", plan)
        self.assertEqual(rows[0]["url"], "https://github.com/openclaw/openclaw")
        self.assertTrue(any("live repository match could not be verified" in item for item in list((handler.last_browse_report or {}).get("limitations") or [])))

    async def test_github_browse_remote_inspection_avoids_clone_cleanup_note(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="check out openclaw on github",
            query_variants=["site:github.com openclaw"],
            reason="github_lookup",
        )
        discovery_rows = [
            {
                "title": "GitHub - openclaw/openclaw",
                "url": "https://github.com/openclaw/openclaw",
                "description": "OpenClaw repo.",
                "source": "searxng",
            }
        ]
        inspection = GitHubInspection(
            repo_url="https://github.com/openclaw/openclaw",
            repo_slug="openclaw/openclaw",
            default_branch="main",
            latest_commit="2026-03-16",
            readme_excerpt="OpenClaw is a personal AI assistant.",
            manifests={"package.json": "name=openclaw"},
            sources=["https://github.com/openclaw/openclaw"],
            summary="openclaw/openclaw is a GitHub repository. Default branch: main. Detected manifests: package.json.",
            inspection_method="remote",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=discovery_rows)):
            with patch("workshop.toolbox.stacks.web_core.websearch.inspect_github_repository", return_value=inspection):
                with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                    rows = await handler._github_browse("check out openclaw on github", plan)
        self.assertEqual(rows[0]["url"], "https://github.com/openclaw/openclaw")
        self.assertFalse(list((handler.last_browse_report or {}).get("limitations") or []))
        steps = list((handler.last_browse_report or {}).get("execution_steps") or [])
        self.assertTrue(any("via remote fetch" in step for step in steps))

    async def test_github_browse_single_repo_skips_unrelated_support_rows(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="check out openclaw on github",
            query_variants=["site:github.com openclaw"],
            reason="github_lookup",
        )
        discovery_rows = [
            {
                "title": "GitHub - openclaw/openclaw",
                "url": "https://github.com/openclaw/openclaw",
                "description": "OpenClaw repo.",
                "source": "ddg",
            },
            {
                "title": "GitHub - awiseguy88/openclaw-advanced-skills-library",
                "url": "https://github.com/awiseguy88/openclaw-advanced-skills-library",
                "description": "Another repo with openclaw in the name.",
                "source": "ddg",
            },
            {
                "title": "Install - OpenClaw",
                "url": "https://docs.openclaw.dev/install",
                "description": "Install guide for OpenClaw.",
                "source": "ddg",
            },
            {
                "title": "The openclaw from openclaw - GithubHelp",
                "url": "https://githubhelp.com/openclaw/openclaw",
                "description": "Generic mirrored help page.",
                "source": "ddg",
            },
        ]
        inspection = GitHubInspection(
            repo_url="https://github.com/openclaw/openclaw",
            repo_slug="openclaw/openclaw",
            default_branch="main",
            latest_commit="2026-03-17 | abc1234 | test",
            readme_excerpt="OpenClaw helps automate research and browsing.",
            manifests={"package.json": "name=openclaw"},
            tags=["v0.1.0"],
            sources=["https://github.com/openclaw/openclaw"],
            summary="openclaw/openclaw is a GitHub repository. Default branch: main.",
            inspection_method="remote",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=discovery_rows)):
            with patch("workshop.toolbox.stacks.web_core.websearch.inspect_github_repository", return_value=inspection):
                with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                    rows = await handler._github_browse("check out openclaw on github", plan)
        urls = [str((row or {}).get("url") or "") for row in rows]
        self.assertIn("https://github.com/openclaw/openclaw", urls)
        self.assertIn("https://docs.openclaw.dev/install", urls)
        self.assertNotIn("https://github.com/awiseguy88/openclaw-advanced-skills-library", urls)
        self.assertNotIn("https://githubhelp.com/openclaw/openclaw", urls)

    async def test_github_compare_recovery_keeps_selected_repo_row_when_one_inspection_fails(self) -> None:
        handler = WebSearchHandler()
        plan = BrowsePlan(
            mode="github",
            query="compare openclaw and deer-flow on github",
            query_variants=["site:github.com openclaw deer-flow"],
            reason="github_lookup",
        )
        discovery_rows = [
            {
                "title": "openclaw/openclaw on GitHub",
                "url": "https://github.com/openclaw/openclaw",
                "description": "OpenClaw repo.",
                "source": "searxng",
            },
            {
                "title": "bytedance/deer-flow on GitHub",
                "url": "https://github.com/bytedance/deer-flow",
                "description": "DeerFlow repo.",
                "source": "searxng",
            },
            {
                "title": "GitHub Topics: agent",
                "url": "https://github.com/topics/agent",
                "description": "Topic page.",
                "source": "searxng",
            },
        ]
        inspection = GitHubInspection(
            repo_url="https://github.com/openclaw/openclaw",
            repo_slug="openclaw/openclaw",
            default_branch="main",
            latest_commit="2026-03-17",
            readme_excerpt="OpenClaw is a personal AI assistant.",
            manifests={"package.json": "name=openclaw"},
            sources=["https://github.com/openclaw/openclaw"],
            summary="openclaw/openclaw is a GitHub repository. Default branch: main.",
            inspection_method="remote",
        )
        with patch("workshop.toolbox.stacks.web_core.websearch.search_general", AsyncMock(return_value=discovery_rows)):
            with patch(
                "workshop.toolbox.stacks.web_core.websearch.inspect_github_repository",
                side_effect=[inspection, RuntimeError("deer-flow fetch failed")],
            ):
                with patch.object(handler, "_write_agentpedia_memory", return_value=0):
                    rows = await handler._github_browse("compare openclaw and deer-flow on github", plan)
        urls = [str((row or {}).get("url") or "") for row in rows]
        self.assertIn("https://github.com/openclaw/openclaw", urls)
        self.assertIn("https://github.com/bytedance/deer-flow", urls)
        self.assertNotIn("https://github.com/topics/agent", urls)

    async def test_write_agentpedia_memory_persists_rows(self) -> None:
        handler = WebSearchHandler()

        class _FakeResearched:
            def add_facts(self, facts, domain=None):
                return 1

        class _FakeAgentpedia:
            def __init__(self) -> None:
                self.researched = _FakeResearched()
                self.facts = []

            def add_facts(self, facts):
                self.facts.extend(list(facts or []))
                return {"added_count": 2}

        handler.agentpedia = _FakeAgentpedia()
        added = handler._write_agentpedia_memory(
            "latest WHO dengue treatment guidance",
            [
                {
                    "title": "WHO dengue guidance",
                    "url": "https://www.who.int/publications/i/item/9789240093590",
                    "description": "2025 arboviral disease guideline.",
                }
            ],
            domain_hint="biomed",
        )
        self.assertEqual(added, 3)

    async def test_agentpedia_memory_filters_python_release_preview_pages(self) -> None:
        handler = WebSearchHandler()

        class _FakeAgentpediaLookup:
            def search_agentpedia(self, query, k=8, tags=None):
                return [
                    {
                        "source_title": "Python Release Python 3.13.0a4 | Python.org",
                        "source_url": "https://www.python.org/downloads/release/python-3130a4/",
                        "claim": "Alpha release preview page.",
                    },
                    {
                        "source_title": "What's New In Python 3.13",
                        "source_url": "https://docs.python.org/3/whatsnew/3.13.html",
                        "claim": "Python 3.13 documentation release highlights.",
                    },
                ]

        handler.agentpedia = _FakeAgentpediaLookup()
        rows = handler._agentpedia_memory_rows("what changed in python 3.13 docs", limit=4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://docs.python.org/3/whatsnew/3.13.html")

    async def test_write_agentpedia_memory_skips_python_release_preview_pages(self) -> None:
        handler = WebSearchHandler()

        class _FakeResearched:
            def add_facts(self, facts, domain=None):
                return len(list(facts or []))

        class _FakeAgentpedia:
            def __init__(self) -> None:
                self.researched = _FakeResearched()
                self.fact_calls = []

            def add_facts(self, facts):
                self.fact_calls.append(list(facts or []))
                return {"added_count": len(list(facts or []))}

        fake = _FakeAgentpedia()
        handler.agentpedia = fake
        added = handler._write_agentpedia_memory(
            "what changed in python 3.13 docs",
            [
                {
                    "title": "Python Release Python 3.13.0a4 | Python.org",
                    "url": "https://www.python.org/downloads/release/python-3130a4/",
                    "description": "Alpha release preview page.",
                }
            ],
            domain_hint="software",
        )
        self.assertEqual(added, 0)

    async def test_search_bundle_carries_browse_summary(self) -> None:
        handler = WebSearchHandler()
        handler.last_browse_report = {
            "query": "openclaw github",
            "summary": "OpenClaw is a GitHub repository.",
            "limitations": ["Temporary repository clone cleaned up after inspection."],
            "execution_steps": ["plan: mode=github", "read: inspected README and manifests for 1 repo(s)"],
        }
        bundle = handler.to_search_bundle(
            "openclaw github",
            [{"title": "OpenClaw", "url": "https://github.com/openclaw/openclaw", "description": "Repo"}],
        )
        self.assertIn("GitHub repository", bundle.summary)
        self.assertTrue(bundle.warnings)
        self.assertTrue(bundle.execution_trace)

    async def test_search_bundle_prefers_page_content_for_python_docs_queries(self) -> None:
        handler = WebSearchHandler()
        bundle = handler.to_search_bundle(
            "what changed in python 3.13 docs",
            [
                {
                    "title": "What's New In Python 3.13",
                    "url": "https://docs.python.org/3/whatsnew/3.13.html",
                    "description": "(PEP written and implementation contributed by Malcolm Smith in gh-116622.)",
                    "content": (
                        "What’s New In Python 3.13. Python 3.13 was released on October 7, 2024. "
                        "The biggest changes include a new interactive interpreter, experimental free-threaded mode, and an experimental JIT compiler."
                    ),
                    "source": "searxng",
                }
            ],
        )
        self.assertIn("interactive interpreter", bundle.results[0].snippet)

    async def test_format_results_includes_execution_trace(self) -> None:
        handler = WebSearchHandler()
        handler.last_browse_report = {
            "query": "openclaw github",
            "summary": "OpenClaw is a GitHub repository.",
            "limitations": [],
            "execution_steps": ["plan: mode=github", "read: inspected README and manifests for 1 repo(s)"],
        }
        rendered = handler.format_results(
            [{"title": "OpenClaw", "url": "https://github.com/openclaw/openclaw", "description": "Repo"}]
        )
        self.assertIn("Agent trace:", rendered)
        self.assertIn("1. plan: mode=github", rendered)

    async def test_append_browse_step_records_recovery_notes(self) -> None:
        handler = WebSearchHandler()
        handler._append_browse_step(
            "latest WHO dengue treatment guidance",
            step="retry",
            detail="falling back to DDG after the official query returned 0 rows",
            mode="deep",
        )
        report = handler.last_browse_report or {}
        events = list(report.get("execution_events") or [])
        self.assertTrue(events)
        self.assertEqual(events[0].get("status"), "recovery")
        self.assertIn("falling back to DDG", " ".join(report.get("recovery_notes") or []))

    async def test_official_rows_adequacy_requires_stronger_recency_signal(self) -> None:
        handler = WebSearchHandler()
        adequate = handler._official_rows_adequate(
            "latest ACC/AHA hypertension guideline",
            [
                {
                    "title": "High Blood Pressure Guideline",
                    "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                    "description": "Official guideline page.",
                }
            ],
        )
        self.assertFalse(adequate)

    async def test_official_result_satisfies_query_rejects_unrelated_cardio_doi_pages(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._official_result_satisfies_query(
            "what are the latest hypertension guidelines",
            {
                "title": "ahajournals.org/doi/10.1161/CIR.0000000000001309",
                "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309",
                "description": "2025 editorial page for another cardiology article.",
            },
        )
        self.assertFalse(allowed)

    async def test_who_dengue_latest_queries_require_recent_who_match_before_stopping(self) -> None:
        handler = WebSearchHandler()
        recent_cdc = handler._official_result_satisfies_query(
            "latest WHO dengue treatment guidance",
            {
                "title": "Dengue Case Management Presumptive Diagnosis",
                "url": "https://www.cdc.gov/dengue/media/pdfs/2024/05/20240521_342849-B_PRESS_READY_PocketGuideDCMC_UPDATE.pdf",
                "description": "2024 CDC dengue case management pocket guide.",
            },
        )
        recent_who = handler._official_result_satisfies_query(
            "latest WHO dengue treatment guidance",
            {
                "title": "New WHO guidelines for clinical management of arboviral diseases: dengue, chikungunya, Zika and yellow fever",
                "url": "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                "description": "2025 WHO arboviral diseases guideline update.",
            },
        )
        self.assertFalse(recent_cdc)
        self.assertTrue(recent_who)

    async def test_who_country_guidance_pages_are_rejected_for_global_latest_lookup(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "latest WHO dengue treatment guidance",
            {
                "title": "National Guideline for Clinical Management of Dengue 2022",
                "url": "https://www.who.int/timorleste/publications/national-guideline-for-clinical-management-of-dengue-2022",
                "description": "Country guidance page for Timor-Leste.",
            },
        )
        self.assertFalse(allowed)

    async def test_generic_latest_hypertension_rows_need_newer_or_broader_official_coverage(self) -> None:
        handler = WebSearchHandler()
        adequate = handler._official_rows_adequate(
            "what are the latest hypertension guidelines",
            [
                {
                    "title": "2024 Elevated Blood Pressure and Hypertension",
                    "url": "https://www.escardio.org/guidelines/clinical-practice-guidelines/all-esc-practice-guidelines/elevated-blood-pressure-and-hypertension/",
                    "description": "2024 ESC guideline page.",
                }
            ],
        )
        self.assertFalse(adequate)

    async def test_search_web_records_execution_steps_for_quick_mode(self) -> None:
        handler = WebSearchHandler()
        quick_results = [
            {"href": "https://example.com/a", "title": "Example A", "body": "Example body A"},
            {"href": "https://example.com/b", "title": "Example B", "body": "Example body B"},
            {"href": "https://example.com/c", "title": "Example C", "body": "Example body C"},
        ]
        with patch("workshop.toolbox.stacks.web_core.websearch.build_browse_plan", return_value=BrowsePlan(mode="quick", query="example lookup", query_variants=["example lookup"], reason="simple_lookup")):
            with patch.object(handler, "_ddg_text", AsyncMock(return_value=quick_results)):
                rows = await handler.search_web("example lookup")
        self.assertEqual(len(rows), 3)
        self.assertTrue(handler.last_browse_report)
        self.assertTrue(list(handler.last_browse_report.get("execution_steps") or []))

    async def test_research_scoring_penalizes_off_topic_guidelines(self) -> None:
        handler = WebSearchHandler()
        good = handler._score_research_result(
            "latest hypertension guidelines",
            {
                "title": "2025 Hypertension guideline update",
                "url": "https://www.heart.org/hypertension-guideline",
                "description": "Updated blood pressure guideline.",
            },
        )
        bad = handler._score_research_result(
            "latest hypertension guidelines",
            {
                "title": "2025 APASL fatty liver guideline",
                "url": "https://pubmed.ncbi.nlm.nih.gov/41676778/",
                "description": "Guideline for fatty liver disease.",
            },
        )
        self.assertGreater(good, bad)

    async def test_latest_clinical_prioritization_prefers_focus_match(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_research_results(
            "latest hypertension guidelines",
            [
                {
                    "title": "2025 APASL fatty liver guideline",
                    "url": "https://pubmed.ncbi.nlm.nih.gov/41676778/",
                    "description": "Guideline for fatty liver disease.",
                },
                {
                    "title": "2025 hypertension guideline update",
                    "url": "https://www.heart.org/hypertension-guideline",
                    "description": "Updated blood pressure guideline.",
                },
            ],
        )
        self.assertIn("hypertension", rows[0]["title"].lower())

    async def test_official_browse_prioritization_prefers_primary_domains(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "latest ACC/AHA hypertension guideline",
            [
                {
                    "title": "Case-Based Applications of the 2025 AHA/ACC Guideline",
                    "url": "https://pubmed.ncbi.nlm.nih.gov/41204807/",
                    "description": "PubMed entry for the guideline applications.",
                },
                {
                    "title": "2025 High Blood Pressure Guidelines",
                    "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                    "description": "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("ahajournals.org", rows[0]["url"])

    async def test_official_browse_demotes_session_pages_for_cardio_guidelines(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "latest ACC/AHA hypertension guideline",
            [
                {
                    "title": "Hypertension | AHA/ASA Journals",
                    "url": "https://www.ahajournals.org/hypertension-sessions",
                    "description": "Keynote overview of the 2025 AHA/ACC High Blood Pressure Guideline.",
                },
                {
                    "title": "2025 High Blood Pressure Guidelines",
                    "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                    "description": "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("/doi/", rows[0]["url"])

    async def test_official_browse_demotes_toc_pages_for_cardio_guidelines(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "what are the latest hypertension guidelines",
            [
                {
                    "title": "Vol 0, No 0 | Hypertension",
                    "url": "https://www.ahajournals.org/toc/hyp/0/0",
                    "description": "Issue listing page for Hypertension.",
                },
                {
                    "title": "2025 High Blood Pressure Guidelines",
                    "url": "https://www.ahajournals.org/guidelines/high-blood-pressure",
                    "description": "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("/guidelines/", rows[0]["url"])

    async def test_generic_latest_hypertension_prefers_newer_us_guideline_sources(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "what are the latest hypertension guidelines",
            [
                {
                    "title": "2024 Elevated Blood Pressure and Hypertension",
                    "url": "https://www.escardio.org/guidelines/clinical-practice-guidelines/all-esc-practice-guidelines/elevated-blood-pressure-and-hypertension/",
                    "description": "2024 ESC guideline page.",
                },
                {
                    "title": "2025 High Blood Pressure Guidelines",
                    "url": "https://www.ahajournals.org/doi/full/10.1161/CIR.0000000000001356",
                    "description": "The 2025 AHA/ACC High Blood Pressure Guideline reflects the latest recommendations.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("ahajournals.org", rows[0]["url"])

    async def test_trip_planning_row_filter_rejects_ad_heavy_bing_pages(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "plan a 3 day trip to Tokyo",
            {
                "title": "3 Days Tokyo - Plan Your Tokyo Itinerary",
                "url": "https://www.bing.com/travel",
                "description": "Book now. Reserve now. Has been visited by millions in the past month.",
            },
        )
        self.assertFalse(allowed)

    async def test_travel_lookup_row_filter_rejects_ad_heavy_bing_pages(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "best time to visit Tokyo",
            {
                "title": "Best Time to Visit Tokyo - Top Hotels & Rates",
                "url": "https://www.bing.com/travel",
                "description": "Book now. Reserve now. Top hotels and rates for Tokyo travel.",
            },
        )
        self.assertFalse(allowed)

    async def test_travel_lookup_row_filter_accepts_cost_guide(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "is Tokyo expensive",
            {
                "title": "Tokyo Travel Cost - Average Price of a Vacation to Tokyo",
                "url": "https://www.budgetyourtrip.com/japan/tokyo",
                "description": "Daily cost, prices, and budget guidance for visiting Tokyo.",
            },
        )
        self.assertTrue(allowed)

    async def test_trip_planning_row_filter_rejects_forum_results(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "plan a 3 day trip to Tokyo",
            {
                "title": "Which Tokyo daytrip with teen? - Tokyo Forum - Tripadvisor",
                "url": "https://www.tripadvisor.com/ShowTopic-g298184-i861-k2032256-Which_Tokyo_daytrip_with_teen-Tokyo_Tokyo_Prefecture_Kanto.html",
                "description": "Tokyo travel forum discussion thread.",
            },
        )
        self.assertFalse(allowed)

    async def test_trip_planning_row_filter_rejects_broad_attractions_and_pinterest_rows(self) -> None:
        handler = WebSearchHandler()
        attractions_allowed = handler._row_allowed_for_query(
            "plan a 3 day trip to Tokyo",
            {
                "title": "THE 15 BEST Things to Do in Tokyo (2026) - Must-See Attractions",
                "url": "https://www.tripadvisor.com/Attractions-g298184-Activities-Tokyo_Tokyo_Prefecture_Kanto.html",
                "description": "Broad attractions list for Tokyo.",
            },
        )
        pinterest_allowed = handler._row_allowed_for_query(
            "plan a 3 day trip to Tokyo",
            {
                "title": "3-Day Tokyo Itinerary for First-Time Visitors in 2025",
                "url": "https://www.pinterest.com/pin/demo/",
                "description": "Pinned itinerary graphic.",
            },
        )
        self.assertFalse(attractions_allowed)
        self.assertFalse(pinterest_allowed)

    async def test_trip_planning_row_filter_requires_family_signal_for_family_queries(self) -> None:
        handler = WebSearchHandler()
        generic_allowed = handler._row_allowed_for_query(
            "family trip plan for Paris",
            {
                "title": "Best trip itineraries for Paris",
                "url": "https://www.triphobo.com/trip-planner/paris-france",
                "description": "Explore itinerary templates and trip plans for Paris.",
            },
        )
        family_allowed = handler._row_allowed_for_query(
            "family trip plan for Paris",
            {
                "title": "Three days in Paris with the family",
                "url": "https://parisjetaime.com/en/article/family-trip-paris-a138",
                "description": "Family-friendly Paris plan with museums, activities, and kid-focused stops.",
            },
        )
        self.assertFalse(generic_allowed)
        self.assertTrue(family_allowed)

    async def test_trip_planning_row_filter_requires_food_signal_for_food_queries(self) -> None:
        handler = WebSearchHandler()
        generic_allowed = handler._row_allowed_for_query(
            "food itinerary for Paris",
            {
                "title": "Paris itinerary: how to spend 3 perfect days",
                "url": "https://example.com/paris-itinerary",
                "description": "General first-time Paris itinerary with landmarks and museums.",
            },
        )
        food_allowed = handler._row_allowed_for_query(
            "food itinerary for Paris",
            {
                "title": "3-day Paris itinerary for food lovers",
                "url": "https://parispass.com/en-us/blog/3-day-paris-itinerary-for-food-lovers",
                "description": "Taste your way through Paris with restaurants, bakeries, and markets.",
            },
        )
        self.assertFalse(generic_allowed)
        self.assertTrue(food_allowed)

    async def test_shopping_compare_row_filter_rejects_off_topic_academic_result(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "compare iPhone 16 and Samsung Galaxy S25",
            {
                "title": "Twelve Years of Galaxy Zoo",
                "url": "https://arxiv.org/abs/1910.08177",
                "description": "A study of galaxy morphology.",
            },
        )
        self.assertFalse(allowed)

    async def test_shopping_compare_row_filter_rejects_video_and_variant_mismatch_rows(self) -> None:
        handler = WebSearchHandler()
        youtube_allowed = handler._row_allowed_for_query(
            "compare iPhone 16 and Samsung Galaxy S25",
            {
                "title": "iPhone 16 vs Galaxy S25 - video review",
                "url": "https://www.youtube.com/watch?v=demo",
                "description": "A video comparison.",
            },
        )
        mismatch_allowed = handler._row_allowed_for_query(
            "compare iPhone 16 and Samsung Galaxy S25",
            {
                "title": "Samsung Galaxy S25 vs. Apple iPhone 16 Pro - GSMArena.com news",
                "url": "https://www.gsmarena.com/samsung_galaxy_s25_vs_apple_iphone_16_pro_review_battery_camera_price_compared-news-66490.php",
                "description": "Comparison article for the S25 and iPhone 16 Pro.",
            },
        )
        self.assertFalse(youtube_allowed)
        self.assertFalse(mismatch_allowed)

    async def test_shopping_compare_row_filter_rejects_compact_variant_mismatch_and_third_device_showdown(self) -> None:
        handler = WebSearchHandler()
        compact_variant_allowed = handler._row_allowed_for_query(
            "difference between iPhone 16 and Samsung Galaxy S25",
            {
                "title": "SamsungGalaxyS25UltravsiPhone16Pro Max... - PhoneArena",
                "url": "https://www.phonearena.com/reviews/samsunggalaxys25ultravsiphone16promax",
                "description": "Head-to-head between the Ultra and Pro Max models.",
            },
        )
        third_device_allowed = handler._row_allowed_for_query(
            "pros and cons of iPhone 16 vs Samsung Galaxy S25",
            {
                "title": "AI smartphone features compared - iPhone 16 vs. Samsung Galaxy S25 vs. Google Pixel 9",
                "url": "https://www.tomsguide.com/phones/ai-smartphone-features-compared-iphone-16-vs-samsung-galaxy-s25-vs-google-pixel-9",
                "description": "Three-way comparison across Apple, Samsung, and Google phones.",
            },
        )
        self.assertFalse(compact_variant_allowed)
        self.assertFalse(third_device_allowed)

    async def test_shopping_compare_prioritization_prefers_real_review_over_galaxy_zoo(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "compare iPhone 16 and Samsung Galaxy S25",
            [
                {
                    "title": "Twelve Years of Galaxy Zoo",
                    "url": "https://arxiv.org/abs/1910.08177",
                    "description": "A study of galaxy morphology.",
                },
                {
                    "title": "iPhone 16 vs Samsung Galaxy S25: Which is better?",
                    "url": "https://www.techradar.com/phones/iphone-16-vs-samsung-galaxy-s25",
                    "description": "Comparison of display, battery life, cameras, and value.",
                },
            ],
            prefer_official=False,
        )
        self.assertIn("techradar.com", rows[0]["url"])

    async def test_infer_research_domain_uses_general_for_trip_planning_and_shopping_compare(self) -> None:
        handler = WebSearchHandler()
        self.assertEqual(handler._infer_research_domain("plan a 3 day trip to Tokyo"), "general")
        self.assertEqual(handler._infer_research_domain("should I buy iPhone 16 or Samsung Galaxy S25"), "general")

    async def test_python_docs_row_filter_rejects_nested_wrong_whatsnew_page(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "what changed in python 3.13 docs",
            {
                "title": "What'sNewInPython3.10 -Python3.13.12 documentation",
                "url": "https://docs.python.org/3.13/whatsnew/3.10.html",
                "description": "Nested older page within the 3.13 docs tree.",
            },
        )
        self.assertFalse(allowed)

    async def test_python_docs_row_filter_rejects_other_sections_even_same_minor_version(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "what changed in python 3.13 docs",
            {
                "title": "2to3 - Automated Python 2 to 3 code translation -",
                "url": "https://docs.python.org/3.13/library/2to3.html",
                "description": "Python 3.13 documentation page outside What's New or changelog.",
            },
        )
        self.assertFalse(allowed)

    async def test_who_guideline_prioritization_demotes_generic_topic_pages(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "latest WHO dengue treatment guidance",
            [
                {
                    "title": "Dengue and severe dengue",
                    "url": "https://www.who.int/health-topics/dengue-and-severe-dengue",
                    "description": "WHO topic overview page.",
                },
                {
                    "title": "New WHO guidelines for clinical management of arboviral diseases: dengue, chikungunya, Zika and yellow fever",
                    "url": "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                    "description": "2025 WHO arboviral diseases guideline update.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("/news/item/", rows[0]["url"])

    async def test_who_guideline_prioritization_prefers_2025_publication_over_older_handbook(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "latest WHO dengue treatment guidance",
            [
                {
                    "title": "Handbook for clinical management of dengue WHO and Special",
                    "url": "https://www.who.int/publications/i/item/9789241504713",
                    "description": "Older WHO dengue handbook page.",
                },
                {
                    "title": "WHO guidelines for clinical management of arboviral diseases",
                    "url": "https://www.who.int/publications/i/item/9789240111110",
                    "description": "Jul 4, 2025 WHO publication page for the new arboviral guideline.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("9789240111110", rows[0]["url"])

    async def test_python_docs_prioritization_prefers_requested_version(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "what changed in python 3.13 docs",
            [
                {
                    "title": "What's New In Python 3.12",
                    "url": "https://docs.python.org/3/whatsnew/3.12.html",
                    "description": "Python 3.12 docs release notes.",
                },
                {
                    "title": "What's New In Python 3.13",
                    "url": "https://docs.python.org/3/whatsnew/3.13.html",
                    "description": "Python 3.13 docs release notes.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("/3.13.html", rows[0]["url"])

    async def test_software_change_row_filter_rejects_other_versions(self) -> None:
        handler = WebSearchHandler()
        allowed = handler._row_allowed_for_query(
            "summarize kubernetes 1.32 changelog",
            {
                "title": "Kubernetes v1.35: Timbernetes (The World Tree Release)",
                "url": "https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/",
                "description": "Release notes for Kubernetes 1.35.",
            },
        )
        self.assertFalse(allowed)

    async def test_software_change_version_match_rejects_neighboring_version_suffix(self) -> None:
        handler = WebSearchHandler()
        self.assertFalse(handler._software_change_version_matches("2.3", "What's new in 2.2.3 - pandas"))
        self.assertTrue(handler._software_change_version_matches("2.3", "What's new in 2.3.2 - pandas"))

    async def test_software_change_prioritization_prefers_requested_version(self) -> None:
        handler = WebSearchHandler()
        rows = handler._prioritize_browse_rows(
            "summarize kubernetes 1.32 changelog",
            [
                {
                    "title": "Kubernetes v1.35: Timbernetes (The World Tree Release)",
                    "url": "https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/",
                    "description": "Release notes for Kubernetes 1.35.",
                },
                {
                    "title": "Kubernetes v1.32: Penelope",
                    "url": "https://kubernetes.io/blog/2024/12/11/kubernetes-v1-32-release/",
                    "description": "Release notes for Kubernetes 1.32.",
                },
            ],
            prefer_official=True,
        )
        self.assertIn("/kubernetes-v1-32-release/", rows[0]["url"])

    async def test_known_official_seed_rows_include_software_release_adapters(self) -> None:
        handler = WebSearchHandler()
        rows = handler._known_official_seed_rows("latest typescript 5.8 release notes")
        urls = {str((row or {}).get("url") or "") for row in rows}
        self.assertIn("https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html", urls)

        rows = handler._known_official_seed_rows("what changed in rust 1.84 docs")
        urls = {str((row or {}).get("url") or "") for row in rows}
        self.assertIn("https://blog.rust-lang.org/releases/1.84.0", urls)
        self.assertIn("https://doc.rust-lang.org/releases.html", urls)

        rows = handler._known_official_seed_rows("what's new in docker compose")
        urls = {str((row or {}).get("url") or "") for row in rows}
        self.assertIn("https://docs.docker.com/compose/release-notes/", urls)


if __name__ == "__main__":
    unittest.main()
