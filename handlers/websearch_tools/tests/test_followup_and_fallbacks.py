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


def test_followup_resolver_rewrites_low_confidence_followup_without_meta():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u3", "news", "latest news", [
        {"title": "Economy update", "url": "https://a.example.com", "description": "A"},
        {"title": "Sports round-up", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u3")
    r = FollowUpResolver().resolve("tell me more about that one", ctx)
    assert r is not None
    assert r.action == "rewrite_query"
    assert "Previous query:" not in r.rewritten_query
    assert "decide whether" not in r.rewritten_query.lower()


def test_scalar_float_handles_single_value_series_like():
    from handlers.websearch_tools.finance import _scalar_float

    class _One:
        def __init__(self, v):
            self._v = v
        @property
        def iloc(self):
            class _I:
                def __init__(self, v):
                    self.v = v
                def __getitem__(self, idx):
                    return self.v
            return _I(self._v)

    assert _scalar_float(_One(123.45)) == 123.45


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


def test_followup_resolver_finance_temporal_rewrite_uses_subject():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u4", "finance", "what's the price of bitcoin", [{"title": "BTC", "url": "https://btc.example", "description": "A"}], finance_intent="crypto")
    ctx = store.get("u4")
    r = FollowUpResolver().resolve("what was its price in 2021", ctx)
    assert r is not None
    assert r.action == "rewrite_query"
    assert r.rewritten_query.lower() == "bitcoin price 2021"


def test_tool_context_finance_intent_and_selection_tracking():
    store = ToolContextStore(ttl_seconds=60)
    store.set(
        "u5",
        "finance",
        "price of bitcoin",
        [
            {"title": "Story A", "url": "https://a.example.com", "description": "A"},
            {"title": "Story B", "url": "https://b.example.com", "description": "B"},
        ],
        finance_intent="crypto",
    )
    store.mark_selected("u5", rank=2)
    ctx = store.get("u5")
    assert ctx is not None
    assert ctx.last_finance_intent == "crypto"
    assert ctx.last_selected_rank == 2
    assert ctx.last_selected_url.endswith("b.example.com")


def test_followup_mode_switch_explanation_does_not_bind_to_last_result():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u_mode", "news", "latest climate news", [
        {"title": "Climate policy update", "url": "https://a.example.com", "description": "A"},
        {"title": "Energy market outlook", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u_mode")
    resolver = FollowUpResolver()

    assert resolver.is_mode_switch_explanation("teach me about diffusion models") is True
    assert resolver.is_explicit_reference("teach me about diffusion models") is False

    r = resolver.resolve("teach me about diffusion models", ctx)
    assert r is None


def test_followup_explicit_reference_summarize_second_result_binds():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u_bind_1", "news", "latest ai news", [
        {"title": "Story A", "url": "https://a.example.com", "description": "A"},
        {"title": "Story B", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u_bind_1")
    resolver = FollowUpResolver()

    assert resolver.is_explicit_reference("summarize the 2nd result") is True
    r = resolver.resolve("summarize the 2nd result", ctx)
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert r.url.endswith("b.example.com")


def test_followup_explicit_reference_expand_headline_two_binds():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u_bind_2", "news", "latest ai headlines", [
        {"title": "Story A", "url": "https://a.example.com", "description": "A"},
        {"title": "Story B", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u_bind_2")
    resolver = FollowUpResolver()

    assert resolver.is_explicit_reference("expand headline 2") is True
    r = resolver.resolve("expand headline 2", ctx)
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert r.url.endswith("b.example.com")


def test_historical_search_adequacy_check_flags_inadequate_answer():
    from handlers.websearch_tools.historical_search import cheap_adequacy_check

    q = "what was the price of oil in nov 2022"
    bad = "Oil prices changed a lot over time."
    good = "In Nov 2022, Brent crude traded mostly around $85-$95 per barrel, with many sessions near $90."

    assert cheap_adequacy_check(q, bad) is False
    assert cheap_adequacy_check(q, good) is True


def test_historical_search_sanitizer_removes_injection_markers():
    from handlers.websearch_tools.historical_search import sanitize_final_output

    dirty = "Previous query: foo\nPrevious top result: bar\n<think>x</think>Answer\n\n\nDone"
    clean = sanitize_final_output(dirty)
    assert "Previous query:" not in clean
    assert "Previous top result:" not in clean
    assert "<think>" not in clean.lower()
    assert "Answer" in clean


def test_maybe_enrich_historical_answer_uses_subprocess_payload(monkeypatch):
    from handlers.websearch_tools import historical_search as hs

    class _Proc:
        returncode = 0
        async def communicate(self):
            return (b'{"answer": "enriched answer"}', b"")

    async def fake_exec(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    out = asyncio.run(hs.maybe_enrich_historical_answer("what was the price of oil in nov 2022", "short"))
    assert out == "enriched answer"
