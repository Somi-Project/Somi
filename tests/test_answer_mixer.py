from handlers.search_bundle import SearchBundle
from routing.types import QueryPlan, TimeAnchor
from synthesis.answer_mixer import mix_answer


def test_year_request_no_recency_words_when_evidence_disabled():
    plan = QueryPlan(
        mode="LLM_ONLY",
        needs_recency=False,
        time_anchor=TimeAnchor(kind="year", year=2022, label="2022"),
        domain="finance",
        evidence_enabled=False,
        search_query="",
        reason="historical_time_anchor",
        confidence=0.9,
    )
    out = mix_answer("what was X in 2022", plan, "latest estimate was 10 in market", None)
    assert "2022" in out
    assert "latest" not in out.lower()
    assert "current" not in out.lower()


def test_warnings_trigger_uncertainty_and_no_invented_numbers():
    plan = QueryPlan(
        mode="SEARCH_ONLY",
        needs_recency=True,
        time_anchor=TimeAnchor(kind="date", date="2022-06-18", label="2022-06-18"),
        domain="finance",
        evidence_enabled=True,
        search_query="",
        reason="historical_exactness",
        confidence=0.9,
    )
    bundle = SearchBundle(query="q", results=[], warnings=["No clearly time-anchored sources found."])
    out = mix_answer("", plan, "", bundle)
    assert "not fully confident" in out.lower() or "uncertain" in out.lower()
    assert not any(ch.isdigit() for ch in out)
