from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import workshop.tools.crawlies as crawlies


class CrawliesUnitTests(unittest.TestCase):
    def test_build_query_variants(self):
        q = "whats the latest hypertension guidelines"
        variants = crawlies.build_query_variants(q)
        self.assertGreaterEqual(len(variants), 3)
        self.assertEqual(len(variants), len(set(v.lower() for v in variants)))



    def test_canonicalize_url_strips_tracking(self):
        url = "https://example.com/a?utm_source=x&x=1&fbclid=abc"
        got = crawlies.canonicalize_url(url)
        self.assertIn("x=1", got)
        self.assertNotIn("utm_source", got)
        self.assertNotIn("fbclid", got)

    def test_score_content_quality_increases_with_signal(self):
        weak = crawlies.CrawlDoc(
            url="https://example.com",
            title="note",
            snippet="short",
            content="tiny",
            method="httpx",
        )
        strong = crawlies.CrawlDoc(
            url="https://www.cdc.gov/hypertension/guidelines",
            title="2025 Hypertension Guideline Statement",
            snippet="official guideline update",
            content=("This guideline statement updates recommendations. " * 60),
            method="pdfplumber",
        )
        sw = crawlies.score_content_quality("latest hypertension guidelines", weak)
        ss = crawlies.score_content_quality("latest hypertension guidelines", strong)
        self.assertGreater(ss, sw)

    def test_fetch_scrapling_handles_missing_browserforge(self):
        cfg = crawlies.CrawliesConfig(use_scrapling=True, use_scrapling_service=False, use_playwright=False, save_artifacts=False)
        engine = crawlies.CrawliesEngine(cfg)
        candidate = crawlies.Candidate(
            url="https://example.com",
            title="Example",
            snippet="snippet",
            query_variant="q",
            page_no=1,
        )

        class _BrokenFetchers:
            def __getattr__(self, name):
                raise ModuleNotFoundError("No module named 'browserforge'")

        with patch("crawlies.importlib.import_module", return_value=_BrokenFetchers()):
            doc = asyncio.run(engine._fetch_scrapling(candidate))

        self.assertEqual(doc.method, "scrapling")
        self.assertIn("all_fetchers_failed", str(doc.error))

    def test_fetch_scrapling_prefers_service_when_available(self):
        cfg = crawlies.CrawliesConfig(
            use_scrapling=False,
            use_scrapling_service=True,
            scrapling_service_url="http://localhost:9959",
            use_playwright=False,
            save_artifacts=False,
        )
        engine = crawlies.CrawliesEngine(cfg)
        candidate = crawlies.Candidate(
            url="https://example.com",
            title="Example",
            snippet="snippet",
            query_variant="q",
            page_no=1,
        )

        engine._fetch_scrapling_service = AsyncMock(return_value=crawlies.CrawlDoc(
            url=candidate.url,
            title=candidate.title,
            snippet=candidate.snippet,
            content="service extracted text",
            method="scrapling_service",
            status_code=200,
        ))

        doc = asyncio.run(engine._fetch_scrapling(candidate))
        self.assertEqual(doc.method, "scrapling_service")
        self.assertIn("service extracted text", doc.content)

    def test_check_scrapling_service_offline_disables_service_path(self):
        cfg = crawlies.CrawliesConfig(
            use_scrapling=False,
            use_scrapling_service=True,
            scrapling_service_url="http://localhost:9959",
            use_playwright=False,
            save_artifacts=False,
            scrapling_service_timeout_s=0.3,
        )
        engine = crawlies.CrawliesEngine(cfg)

        async def _run():
            with patch("crawlies.socket.create_connection", side_effect=OSError("offline")):
                ok = await engine._check_scrapling_service()
                return ok

        ok = asyncio.run(_run())
        self.assertFalse(ok)

        candidate = crawlies.Candidate(
            url="https://example.com",
            title="Example",
            snippet="snippet",
            query_variant="q",
            page_no=1,
        )
        doc = asyncio.run(engine._fetch_scrapling_service(candidate))
        self.assertEqual(doc.method, "scrapling_service")
        self.assertIn("service_unavailable", str(doc.error))

    def test_pipeline_with_mocked_steps(self):
        cfg = crawlies.CrawliesConfig(
            save_artifacts=False,
            max_open_links=3,
            use_scrapling=False,
            use_playwright=False,
            use_llm_rerank=False,
            log_level="DEBUG",
        )
        engine = crawlies.CrawliesEngine(cfg)

        fake_candidates = [
            crawlies.Candidate(
                url=f"https://example.com/{i}",
                title=f"Title {i}",
                snippet="snippet",
                query_variant="q",
                page_no=1,
                score=10 - i,
            )
            for i in range(4)
        ]

        async def fake_crawl_candidate(query: str, candidate: crawlies.Candidate, ordinal: int) -> crawlies.CrawlDoc:
            return crawlies.CrawlDoc(
                url=candidate.url,
                title=candidate.title,
                snippet=candidate.snippet,
                content=("content " * (15 - ordinal)).strip(),
                method="httpx",
                quality=float(20 - ordinal),
                duration_ms=10.0,
            )

        engine.discover_candidates = AsyncMock(return_value=fake_candidates)
        engine.crawl_candidate = AsyncMock(side_effect=fake_crawl_candidate)

        out = asyncio.run(engine.crawl("test query"))
        self.assertIn("docs", out)
        self.assertEqual(len(out["docs"]), 3)
        self.assertGreaterEqual(out["docs"][0]["quality"], out["docs"][1]["quality"])

    def test_artifact_written(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = crawlies.CrawliesConfig(
                save_artifacts=True,
                artifact_dir=td,
                max_open_links=1,
                use_scrapling=False,
                use_playwright=False,
                use_llm_rerank=False,
            )
            engine = crawlies.CrawliesEngine(cfg)

            fake_candidates = [
                crawlies.Candidate(
                    url="https://example.com/1",
                    title="Title",
                    snippet="snippet",
                    query_variant="q",
                    page_no=1,
                    score=10,
                )
            ]

            async def fake_crawl_candidate(query: str, candidate: crawlies.Candidate, ordinal: int) -> crawlies.CrawlDoc:
                return crawlies.CrawlDoc(
                    url=candidate.url,
                    title=candidate.title,
                    snippet=candidate.snippet,
                    content="useful content " * 50,
                    method="httpx",
                    quality=55.0,
                )

            engine.discover_candidates = AsyncMock(return_value=fake_candidates)
            engine.crawl_candidate = AsyncMock(side_effect=fake_crawl_candidate)

            out = asyncio.run(engine.crawl("artifact check"))
            path = out.get("artifact_path")
            self.assertTrue(path)
            self.assertTrue(os.path.exists(path))

            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload.get("query"), "artifact check")





@unittest.skipUnless(os.getenv("CRAWLIES_LIVE") == "1", "Set CRAWLIES_LIVE=1 to run live SearX smoke")
class CrawliesLiveSmokeTests(unittest.TestCase):
    def test_live_query(self):
        cfg = crawlies.CrawliesConfig(
            max_pages=1,
            max_candidates=6,
            max_open_links=2,
            use_scrapling=False,
            use_playwright=False,
            use_llm_rerank=False,
            save_artifacts=False,
        )
        engine = crawlies.CrawliesEngine(cfg)
        out = asyncio.run(engine.crawl("latest hypertension guidelines"))
        self.assertIn("candidates", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
