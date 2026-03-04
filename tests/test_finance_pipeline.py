from datetime import date, datetime
import importlib
import sys
import types

from handlers.finance.compute_summary import compute_historical_summary
from handlers.finance.format_query import normalize_query_spec
from handlers.followup_resolver import FollowUpResolver
from routing.followup import PrevTurnState, can_reuse_evidence


def test_normalize_query_spec_historical_defaults():
    spec = normalize_query_spec(asset_class="equity", symbol="aapl", query_type="historical", now_ts=datetime(2026, 3, 4))
    assert spec.symbol == "AAPL"
    assert spec.interval == "1d"
    assert spec.start == date(2025, 3, 4)
    assert spec.end == date(2026, 3, 4)


def test_compute_historical_summary():
    candles = [
        {"close": 10, "low": 9, "high": 11},
        {"close": 15, "low": 14, "high": 16},
    ]
    out = compute_historical_summary(candles)
    assert out["first_close"] == 10
    assert out["last_close"] == 15
    assert out["min_low"] == 9
    assert out["max_high"] == 16
    assert out["return_pct"] == 50.0


def test_followup_rewrite_prefers_current_subject():
    resolver = FollowUpResolver()

    class Ctx:
        last_query = "What is the current stock price of Apple (AAPL)?"
        last_tool_type = "finance"

    rewritten = resolver._rewrite_followup_query("Now compare its 52-week high/low and recent performance to Tesla (TSLA).", Ctx())
    assert "TSLA" in rewritten


def test_no_reuse_for_finance_symbol_switch():
    prev = PrevTurnState(domain="finance", query="price of AAPL", timestamp=0)
    assert can_reuse_evidence("price of TSLA", prev) is False


def _load_finance_handler_with_stubs(monkeypatch):
    yf_stub = types.SimpleNamespace(Ticker=lambda *_args, **_kwargs: None)
    yq_stub = types.SimpleNamespace(Ticker=lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "yfinance", yf_stub)
    monkeypatch.setitem(sys.modules, "yahooquery", yq_stub)
    pytz_stub = types.SimpleNamespace(timezone=lambda _tz: None)
    monkeypatch.setitem(sys.modules, "pytz", pytz_stub)
    class _ReqSession:
        def get(self, *_args, **_kwargs):
            return None

    requests_stub = types.SimpleNamespace(get=lambda *_args, **_kwargs: None, Session=lambda: _ReqSession())
    monkeypatch.setitem(sys.modules, "requests", requests_stub)

    finance_mod = importlib.import_module("handlers.websearch_tools.finance")
    finance_mod = importlib.reload(finance_mod)
    return finance_mod.FinanceHandler()


def test_historical_detection_blocks_year_query(monkeypatch):
    fh = _load_finance_handler_with_stubs(monkeypatch)
    assert fh._is_historical_query("what was bitcoin price in 2022") is True


def test_historical_unavailable_message_shape(monkeypatch):
    fh = _load_finance_handler_with_stubs(monkeypatch)
    out = fh._historical_unavailable_result()
    assert out[0]["title"] == "Historical Data Not Available"
    assert "not available" in out[0]["description"].lower()
