from datetime import date, datetime

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
