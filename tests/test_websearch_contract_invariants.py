from handlers.followup_resolver import FollowUpResolver
from handlers.routing import decide_route
from handlers.tool_context import ToolContextStore


def test_route_reason_invariant_url_summarize():
    d = decide_route("summarize this url https://example.com/a")
    assert d.route == "websearch"
    assert d.reason == "open_url_and_summarize"


def test_route_reason_invariant_finance_historical_query():
    d = decide_route("what was the price of gold in nov 2022")
    assert d.route == "websearch"
    assert d.reason in {"explicit_or_strong_volatile", "contextual_followup_finance"}


def test_followup_selection_invariant_second_result():
    store = ToolContextStore(ttl_seconds=60)
    store.set("u_contract", "news", "latest news", [
        {"title": "A", "url": "https://a.example.com", "description": "A"},
        {"title": "B", "url": "https://b.example.com", "description": "B"},
    ])
    ctx = store.get("u_contract")
    r = FollowUpResolver().resolve("summarize the 2nd result", ctx)
    assert r is not None
    assert r.action == "open_url_and_summarize"
    assert r.selected_index == 2
    assert r.selected_url.endswith("b.example.com")
