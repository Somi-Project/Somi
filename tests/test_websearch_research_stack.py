from __future__ import annotations

import asyncio
import time

import pytest

class _SlowAgentpedia:
    async def search(self, q: str):
        await asyncio.sleep(0.6)
        return [{"title": "slow", "url": "https://example.com/slow", "description": "slow"}]


def test_research_stack_returns_first_viable_source(monkeypatch):
    pytest.importorskip("httpx")
    pytest.importorskip("duckduckgo_search")
    from handlers.websearch import WebSearchHandler

    ws = WebSearchHandler()
    ws.agentpedia = _SlowAgentpedia()

    async def _fast_searx(client, q, **kwargs):
        return [{"title": "fast", "url": "https://example.com/fast", "description": "fast"}]

    monkeypatch.setattr("handlers.websearch.search_searxng", _fast_searx)

    started = time.monotonic()
    out = asyncio.run(ws._research_stack("test query"))
    elapsed = time.monotonic() - started

    assert out
    assert out[0]["title"] == "fast"
    assert elapsed < 0.5


def test_research_stack_handles_first_completed_exception(monkeypatch):
    pytest.importorskip("httpx")
    pytest.importorskip("duckduckgo_search")
    from handlers.websearch import WebSearchHandler

    ws = WebSearchHandler()

    class _ErrAgentpedia:
        async def search(self, q: str):
            raise RuntimeError("boom")

    ws.agentpedia = _ErrAgentpedia()

    async def _fast_searx(client, q, **kwargs):
        return [{"title": "fallback", "url": "https://example.com/f", "description": "ok"}]

    monkeypatch.setattr("handlers.websearch.search_searxng", _fast_searx)
    out = asyncio.run(ws._research_stack("test query"))
    assert out
    assert out[0]["title"] == "fallback"


def test_research_stack_prefers_agentpedia_when_both_available(monkeypatch):
    pytest.importorskip("httpx")
    pytest.importorskip("duckduckgo_search")
    from handlers.websearch import WebSearchHandler

    ws = WebSearchHandler()

    class _FastAgentpedia:
        async def search(self, q: str):
            return [{"title": "agentpedia", "url": "https://example.com/a", "description": "a"}]

    ws.agentpedia = _FastAgentpedia()

    async def _fast_searx(client, q, **kwargs):
        return [{"title": "searx", "url": "https://example.com/s", "description": "s"}]

    monkeypatch.setattr("handlers.websearch.search_searxng", _fast_searx)
    out = asyncio.run(ws._research_stack("test query"))
    assert out
    assert out[0]["title"] == "agentpedia"
