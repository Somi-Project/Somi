from routing.followup import PrevTurnState
from routing.planner import build_query_plan


def test_historical_bitcoin_nov_2022_is_search_for_finance_data():
    plan = build_query_plan("what was the price of bitcoin nov 2022")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
    assert plan.time_anchor is not None
    assert plan.time_anchor.kind == "month_year"


def test_current_bitcoin_price_is_search_only():
    plan = build_query_plan("what is the latest price of bitcoin")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
    assert plan.needs_recency is True


def test_closing_price_with_sources_prefers_internal_knowledge_when_historical():
    plan = build_query_plan("bitcoin closing price on 2022-06-18 with sources")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
    assert plan.time_anchor is not None
    assert plan.time_anchor.kind == "date"
    assert plan.reason == "historical_finance_requires_data"


def test_personal_query_hardblock_stays_llm_only():
    plan = build_query_plan("what's my reminder for tomorrow")
    assert plan.mode == "LLM_ONLY"
    assert plan.reason == "personal_query_hardblock"


def test_explicit_search_request_forces_search_mode():
    plan = build_query_plan("search online for durable backpacks")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True


def test_prev_state_is_accepted_without_changing_determinism():
    prev = PrevTurnState(domain="weather", query="weather in miami", timestamp=0.0)
    plan = build_query_plan("what's the price of oil", prev)
    assert plan.domain == "finance"
