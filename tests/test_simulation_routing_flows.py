import sys
import types


def _install_stub_modules() -> None:
    if "yfinance" not in sys.modules:
        yf_mod = types.ModuleType("yfinance")

        class _Series:
            def __init__(self, vals):
                self.vals = vals

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

            def __getitem__(self, key):
                data = {
                    "Open": _Series([43000.0, 60000.0]),
                    "High": _Series([48000.0, 67000.0]),
                    "Low": _Series([41000.0, 58000.0]),
                    "Close": _Series([47000.0, 61000.0]),
                }
                return data[key]

        def _download(*args, **kwargs):
            return _FakeHist()

        class _Ticker:
            def __init__(self, *args, **kwargs):
                self.info = {
                    "regularMarketPrice": 62000.0,
                    "shortName": "Bitcoin USD",
                    "currency": "USD",
                }

        yf_mod.download = _download
        yf_mod.Ticker = _Ticker
        sys.modules["yfinance"] = yf_mod

    if "yahooquery" not in sys.modules:
        yq_mod = types.ModuleType("yahooquery")

        class _DummyTicker:
            def __init__(self, *args, **kwargs):
                self.summary_detail = {}
                self.quote_type = {}

        yq_mod.Ticker = _DummyTicker
        sys.modules["yahooquery"] = yq_mod

    if "duckduckgo_search" not in sys.modules:
        ddg_mod = types.ModuleType("duckduckgo_search")

        class _DDGS:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def text(self, query, max_results=8):
                return [{"title": "Fallback", "href": "https://example.com", "body": "fallback"}]

            def news(self, query, max_results=15):
                return [{"title": "Headline 1", "url": "https://news.example.com/1", "snippet": "desc", "date": "2026-01-01"}]

        ddg_mod.DDGS = _DDGS
        sys.modules["duckduckgo_search"] = ddg_mod



    if "requests" not in sys.modules:
        req_mod = types.ModuleType("requests")

        class _Resp:
            status_code = 200

            def json(self):
                return {}

        class _Session:
            def get(self, *args, **kwargs):
                return _Resp()

        req_mod.get = lambda *args, **kwargs: _Resp()
        req_mod.Session = _Session
        sys.modules["requests"] = req_mod

    if "pytz" not in sys.modules:
        pytz_mod = types.ModuleType("pytz")

        class _TZ:
            pass

        pytz_mod.timezone = lambda name: _TZ()
        sys.modules["pytz"] = pytz_mod

    if "httpx" not in sys.modules:
        httpx_mod = types.ModuleType("httpx")

        class _Resp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return {"results": [{"title": "Searx headline", "url": "https://news.example.com/2", "content": "body", "publishedDate": "2026-01-01"}]}

            @property
            def content(self):
                return b""

            @property
            def encoding(self):
                return "utf-8"

            @property
            def url(self):
                return "https://news.example.com/2"

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                return _Resp()

        httpx_mod.AsyncClient = _Client
        sys.modules["httpx"] = httpx_mod


_install_stub_modules()

from handlers.routing import decide_route
from handlers.followup_resolver import FollowUpResolver
from handlers.tool_context import ToolContextStore
from handlers.websearch_tools.finance import FinanceHandler


import pytest
import asyncio


def test_i_general_chat_stays_llm_only():
    d = decide_route("how are you?")
    assert d.route == "llm_only"
    d2 = decide_route("how are you today?")
    assert d2.route == "llm_only"


def test_ii_news_then_natural_followup_resolves_second_link():
    d = decide_route("latest news in trinidad and tobago")
    assert d.route == "websearch"
    assert d.signals.get("intent") == "news"

    store = ToolContextStore(ttl_seconds=300)
    store.set(
        "s1",
        "news",
        "latest news in trinidad and tobago",
        [
            {"title": "Story one", "url": "https://news.example.com/one", "description": "..."},
            {"title": "Story two", "url": "https://news.example.com/two", "description": "..."},
        ],
    )
    r = FollowUpResolver().resolve("can you expand on the second one?", store.get("s1"))
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert r.url.endswith("/two")


def test_iii_weather_routes_to_weather_websearch():
    d = decide_route("weather in port of spain tomorrow")
    assert d.route == "websearch"
    assert d.signals.get("intent") == "weather"


def test_iv_crypto_price_routes_to_crypto_tooling():
    d = decide_route("current price of BTC")
    assert d.route == "websearch"
    assert d.signals.get("intent") == "crypto"


def test_v_crypto_followup_historical_returns_range_not_refusal(monkeypatch):
    fh = FinanceHandler()

    async def fake_search_general(q, min_results=3):
        return [{"title": "Fallback", "url": "https://example.com", "description": "fallback"}]

    monkeypatch.setattr("handlers.websearch_tools.finance.search_general", fake_search_general)
    res = asyncio.run(fh.search_historical_price("what was the price in october 2021", context_symbol="BTC-USD"))
    assert res
    assert res[0].get("source") in {"yfinance_history", "general_search_fallback"}
    assert "historical" in (res[0].get("title") or "").lower() or "fallback" in (res[0].get("source") or "")


def test_contextual_finance_followup_routes_websearch():
    d = decide_route(
        "what was bitcoin price in october 2021",
        agent_state={"last_tool_type": "finance", "has_tool_context": True},
    )
    assert d.route == "websearch"
    assert d.reason == "contextual_followup_finance"


def test_contextual_finance_followup_ignores_unrelated_time_question():
    d = decide_route(
        "what was it in october 2021",
        agent_state={"last_tool_type": "finance", "has_tool_context": True},
    )
    assert d.reason != "contextual_followup_finance"


def test_contextual_weather_followup_routes_weather():
    d = decide_route(
        "tomorrow hourly?",
        agent_state={"last_tool_type": "weather", "has_tool_context": True},
    )
    assert d.route == "websearch"
    assert d.signals.get("intent") == "weather"


def test_ii_news_followup_variant_result_number():
    store = ToolContextStore(ttl_seconds=300)
    store.set(
        "s2",
        "news",
        "latest world news",
        [
            {"title": "Story one", "url": "https://news.example.com/one", "description": "..."},
            {"title": "Story two", "url": "https://news.example.com/two", "description": "..."},
        ],
    )
    r = FollowUpResolver().resolve("open result #2", store.get("s2"))
    assert r is not None and r.url.endswith("/two")


def test_contextual_news_followup_routes_websearch():
    d = decide_route(
        "expand on that story",
        agent_state={"last_tool_type": "news", "has_tool_context": True},
    )
    assert d.route == "websearch"
    assert d.reason == "contextual_followup_news_web"
