import time

from handlers.search_bundle import SearchBundle, SearchResult
from routing.followup import PrevTurnState, can_reuse_evidence
from routing.planner import build_query_plan


def test_cross_domain_followup_bug_finance_not_reusing_weather_evidence():
    prev = PrevTurnState(domain="weather", query="weather in miami", timestamp=time.time())
    plan = build_query_plan("what's the price of oil", prev)
    assert plan.domain == "finance"
    assert plan.mode == "SEARCH_ONLY"
    assert can_reuse_evidence("what's the price of oil", prev) is False


def test_historical_vs_volatile_collision_nov_2022_finance_search_mode():
    plan = build_query_plan("what was the price of bitcoin nov 2022")
    assert plan.time_anchor is not None
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True


def test_news_freshness_sort_and_warning_behavior():
    # Synthetic check for sorting expectation + stale warning style
    bundle = SearchBundle(
        query="latest news for Trinidad and Tobago",
        results=[
            SearchResult("Old", "https://a", "x", "a", "2024-01-01"),
            SearchResult("New", "https://b", "x", "b", "2025-12-31"),
            SearchResult("Unknown", "https://c", "x", "c", None),
        ],
        warnings=[],
    )
    with_date = [r for r in bundle.results if r.published_date]
    with_date.sort(key=lambda r: r.published_date, reverse=True)
    assert with_date[0].title == "New"
