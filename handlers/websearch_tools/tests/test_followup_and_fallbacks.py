import sys
import types

import pytest
import asyncio

if "httpx" not in sys.modules:
    hx = types.ModuleType("httpx")

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b""
        encoding = "utf-8"
        url = "https://example.com"

        def json(self):
            return {"results": []}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, *args, **kwargs):
            return _Resp()

    hx.AsyncClient = _Client
    sys.modules["httpx"] = hx

if "duckduckgo_search" not in sys.modules:
    ddg = types.ModuleType("duckduckgo_search")

    class _DDGS:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def text(self, *args, **kwargs):
            return []
        def news(self, *args, **kwargs):
            return []

    ddg.DDGS = _DDGS
    sys.modules["duckduckgo_search"] = ddg

if "requests" not in sys.modules:
    req_mod = types.ModuleType("requests")

    class _Resp2:
        status_code = 200

        def json(self):
            return {}

    class _Session:
        def get(self, *args, **kwargs):
            return _Resp2()

    req_mod.get = lambda *args, **kwargs: _Resp2()
    req_mod.Session = _Session
    sys.modules["requests"] = req_mod

if "pytz" not in sys.modules:
    pz = types.ModuleType("pytz")
    class _TZ: pass
    pz.timezone = lambda name: _TZ()
    sys.modules["pytz"] = pz

if "ollama" not in sys.modules:
    om = types.ModuleType("ollama")
    om.chat = lambda *args, **kwargs: {"message": {"content": "latest world news today"}}
    sys.modules["ollama"] = om

from handlers.followup_resolver import FollowUpResolver
from handlers.tool_context import ToolContextStore
from handlers.websearch_tools.news import NewsHandler



if "yfinance" not in sys.modules:
    yf_mod = types.ModuleType("yfinance")
    yf_mod.download = lambda *args, **kwargs: None
    yf_mod.Ticker = lambda *args, **kwargs: None
    sys.modules["yfinance"] = yf_mod

if "yahooquery" not in sys.modules:
    yq_mod = types.ModuleType("yahooquery")

    class _DummyTicker:
        def __init__(self, *args, **kwargs):
            self.summary_detail = {}
            self.quote_type = {}

    yq_mod.Ticker = _DummyTicker
    sys.modules["yahooquery"] = yq_mod

from handlers.websearch_tools.finance import FinanceHandler


class _Series:
    def __init__(self, vals):
        self.vals = list(vals)

    def max(self):
        return max(self.vals)

    def min(self):
        return min(self.vals)

    def mean(self):
        return sum(self.vals) / len(self.vals)

    @property
    def iloc(self):
        class _I:
            def __init__(self, vals):
                self.vals = vals

            def __getitem__(self, idx):
                return self.vals[idx]

        return _I(self.vals)


class _FakeHist:
    empty = False

    def __init__(self):
        self.cols = {
            "Open": _Series([43000.0, 60000.0]),
            "High": _Series([48000.0, 67000.0]),
            "Low": _Series([41000.0, 58000.0]),
            "Close": _Series([47000.0, 61000.0]),
        }

    def __getitem__(self, item):
        return self.cols[item]


def test_followup_resolver_ordinal_to_url():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u1", "news", "latest news", [
        {"title": "Story A", "url": "https://a.example.com", "description": "A"},
        {"title": "Story B", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u1")
    r = FollowUpResolver().resolve("expand on the second one", ctx)
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert "b.example.com" in r.url


def test_finance_historical_uses_yfinance_history(monkeypatch):
    fh = FinanceHandler()

    def fake_download(*args, **kwargs):
        return _FakeHist()

    monkeypatch.setattr("handlers.websearch_tools.finance.yf.download", fake_download)
    res = asyncio.run(fh.search_historical_price("what was the price of BTC in october 2021"))
    assert res
    assert res[0]["source"] == "yfinance_history"
    assert "range" in res[0]["description"].lower()


def test_news_searx_to_ddg_fallback(monkeypatch):
    nh = NewsHandler()

    async def fake_searx(*args, **kwargs):
        return []

    async def fake_ddg(*args, **kwargs):
        return [{"title": "DDG Headline", "url": "https://news.example.com", "snippet": "snippet", "date": "2026-01-01"}]

    async def fake_enrich(results, top_n=2):
        return results

    monkeypatch.setattr(nh, "_searx_news", fake_searx)
    monkeypatch.setattr(nh, "_ddg_news", fake_ddg)
    monkeypatch.setattr(nh, "_enrich_top_pages", fake_enrich)

    out = asyncio.run(nh.search_news("latest world news"))
    assert out
    assert out[0].get("provider") == "ddg"


def test_followup_resolver_variant_result_number_and_link_number():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u2", "news", "latest news", [
        {"title": "Story A", "url": "https://a.example.com", "description": "A"},
        {"title": "Story B", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u2")
    r1 = FollowUpResolver().resolve("open result #2", ctx)
    r2 = FollowUpResolver().resolve("summarize link 2", ctx)
    assert r1 and r1.url.endswith("b.example.com")
    assert r2 and r2.url.endswith("b.example.com")


def test_followup_resolver_clarifies_low_confidence_followup():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u3", "news", "latest news", [
        {"title": "Economy update", "url": "https://a.example.com", "description": "A"},
        {"title": "Sports round-up", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u3")
    r = FollowUpResolver().resolve("tell me more about that one", ctx)
    assert r is not None
    assert r.action == "clarify"
    assert r.clarify_options


def test_finance_historical_fallback_without_symbol_uses_query(monkeypatch):
    fh = FinanceHandler()

    def fake_download(*args, **kwargs):
        class _Empty:
            empty = True
        return _Empty()

    captured = {"q": ""}

    async def fake_search_general(q, min_results=3):
        captured["q"] = q
        return [{"title": "Fallback source", "url": "https://example.com", "description": "d"}]

    monkeypatch.setattr("handlers.websearch_tools.finance.yf.download", fake_download)
    monkeypatch.setattr("handlers.websearch_tools.finance.search_general", fake_search_general)
    out = asyncio.run(fh.search_historical_price("what was xyzcoin price in 2021"))
    assert out and out[0].get("source") == "general_search_fallback"
    assert "xyzcoin" in captured["q"].lower()


def test_news_relevance_heuristic_prefers_ddg_when_searx_weak(monkeypatch):
    nh = NewsHandler()

    async def fake_searx(*args, **kwargs):
        return [
            {"title": "Unrelated topic one", "url": "https://s1", "description": "alpha", "provider": "searxng"},
            {"title": "Another unrelated", "url": "https://s2", "description": "beta", "provider": "searxng"},
            {"title": "More unrelated", "url": "https://s3", "description": "gamma", "provider": "searxng"},
        ]

    async def fake_ddg(*args, **kwargs):
        return [{"title": "Global market news", "url": "https://d1", "snippet": "market news today", "date": "2026-01-01"}]

    async def fake_enrich(results, top_n=2):
        return results

    monkeypatch.setattr(nh, "_searx_news", fake_searx)
    monkeypatch.setattr(nh, "_ddg_news", fake_ddg)
    monkeypatch.setattr(nh, "_enrich_top_pages", fake_enrich)

    out = asyncio.run(nh.search_news("market news today"))
    assert out
    assert out[0].get("provider") == "ddg"


def test_news_searx_uses_original_query_not_refined(monkeypatch):
    nh = NewsHandler()
    captured = {"q": ""}

    async def fake_searx(q, max_results=15):
        captured["q"] = q
        return []

    async def fake_ddg(*args, **kwargs):
        return [{"title": "DDG Headline", "url": "https://news.example.com", "snippet": "snippet", "date": "2026-01-01"}]

    async def fake_enrich(results, top_n=2):
        return results

    def fake_refine(q):
        return ("refined altered query", "refined altered query")

    monkeypatch.setattr(nh, "_searx_news", fake_searx)
    monkeypatch.setattr(nh, "_ddg_news", fake_ddg)
    monkeypatch.setattr(nh, "_enrich_top_pages", fake_enrich)
    monkeypatch.setattr(nh, "_refine_query_llm", fake_refine)

    _ = asyncio.run(nh.search_news("what's the price of bitcoin"))
    assert captured["q"] == "what's the price of bitcoin"


def test_crypto_query_is_normalized_before_library_lookup(monkeypatch):
    fh = FinanceHandler()
    captured = {"arg": ""}

    def fake_get_crypto_price(arg):
        captured["arg"] = arg
        return "Bitcoin (BTCUSDT): $100,000"

    monkeypatch.setattr("handlers.websearch_tools.finance.get_crypto_price", fake_get_crypto_price)
    out = asyncio.run(fh.search_crypto_yfinance("what's the price of bitcoin now"))
    assert out
    assert captured["arg"] == "bitcoin"


def test_gold_sentence_maps_to_gc_f_ticker(monkeypatch):
    fh = FinanceHandler()
    captured = {"ticker": ""}

    class _TickerObj:
        def __init__(self, ticker):
            captured["ticker"] = ticker
            self.info = {"regularMarketPrice": 2300.0, "shortName": "Gold Futures", "currency": "USD"}

    monkeypatch.setattr("handlers.websearch_tools.finance.yf.Ticker", _TickerObj)
    monkeypatch.setattr(fh, "get_system_time", lambda: "now")
    out = asyncio.run(fh.search_stocks_commodities("what's the price of gold"))
    assert out
    assert captured["ticker"] == "GC=F"


def test_followup_resolver_phrase_match_selects_single_headline():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u_phrase", "news", "latest news", [
        {"title": "Full support for US action in Iran", "url": "https://a.example.com", "description": "A"},
        {"title": "Another unrelated headline", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u_phrase")
    r = FollowUpResolver().resolve("can you expand on full support for us action in iran", ctx)
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert r.url.endswith("a.example.com")
