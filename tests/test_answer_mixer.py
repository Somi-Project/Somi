from handlers.search_bundle import SearchBundle
from routing.query_plan import QueryPlan
from synthesis.answer_mixer import mix_answer


def test_year_request_no_recency_words_when_evidence_disabled():
    plan = QueryPlan(
        mode="LLM_ONLY",
        needs_recency=False,
        time_anchor={"year": 2022},
        domain="finance",
        evidence_enabled=False,
        rewritten_search_query="",
        reason="historical_year_detected",
    )
    out = mix_answer("what was X in 2022", plan, "latest estimate was 10 in market", None)
    assert "2022" in out
    assert "latest" not in out.lower()
    assert "current" not in out.lower()


def test_warnings_trigger_uncertainty_and_no_invented_numbers():
    plan = QueryPlan(
        mode="SEARCH_ONLY",
        needs_recency=True,
        time_anchor={"date": "2022-06-18"},
        domain="finance",
        evidence_enabled=True,
        rewritten_search_query="",
        reason="exactness_or_citations_override",
    )
    bundle = SearchBundle(query="q", results=[], warnings=["No clearly time-anchored sources found."])
    out = mix_answer("", plan, "", bundle)
    assert "not fully confident" in out.lower() or "uncertain" in out.lower()
    assert not any(ch.isdigit() for ch in out)


def test_recency_mode_keeps_natural_draft_and_adds_sources():
    plan = QueryPlan(
        mode="SEARCH_ONLY",
        needs_recency=True,
        time_anchor=None,
        domain="finance",
        evidence_enabled=True,
        rewritten_search_query="",
        reason="recency_required",
    )
    bundle = SearchBundle(
        query="bitcoin price",
        results=[],
        warnings=[],
    )
    from handlers.search_bundle import SearchResult
    bundle.results.append(SearchResult(title="BTC Price", url="https://example.com/btc", snippet="BTC 100", source_domain="example.com", published_date="2026-01-01"))
    out = mix_answer("", plan, "Bitcoin is trading higher today.", bundle)
    assert "Bitcoin is trading higher today." in out
    assert "Sources:" in out
