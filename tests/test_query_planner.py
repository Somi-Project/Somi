from routing.planner import build_query_plan


def test_historical_bitcoin_2022_is_llm_only():
    plan = build_query_plan("what was the price of bitcoin in 2022")
    assert plan.mode == "LLM_ONLY"
    assert plan.evidence_enabled is False
    assert plan.time_anchor == {"year": 2022}


def test_current_bitcoin_price_is_search_only():
    plan = build_query_plan("what is the price of bitcoin")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
    assert plan.needs_recency is True


def test_closing_price_with_sources_uses_search_and_date_anchor():
    plan = build_query_plan("bitcoin closing price on 2022-06-18 with sources")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
    assert plan.time_anchor == {"date": "2022-06-18"}


def test_current_ceo_is_search_only():
    plan = build_query_plan("who is the current CEO of Apple")
    assert plan.mode == "SEARCH_ONLY"


def test_historical_ceo_is_llm_only():
    plan = build_query_plan("who was the CEO of Apple in 1999")
    assert plan.mode == "LLM_ONLY"


def test_explicit_search_request_forces_search_mode():
    plan = build_query_plan("search online for durable backpacks")
    assert plan.mode == "SEARCH_ONLY"
    assert plan.evidence_enabled is True
