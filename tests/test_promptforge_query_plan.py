from promptforge import PromptForge


def test_promptforge_omits_evidence_when_disabled():
    pf = PromptForge()
    prompt = pf.build_system_prompt(
        identity_block="id",
        current_time="now",
        memory_context="mem",
        search_context="EVIDENCE (top N=6):\n1) x",
        mode_context="Normal",
        evidence_enabled=False,
        query_plan_summary="QUERY_PLAN:\nMODE=LLM_ONLY\nDOMAIN=finance\nNEEDS_RECENCY=false\nTIME_ANCHOR=2022\nEVIDENCE_ENABLED=false\nREASON=historical_time_anchor",
    )
    assert "## EVIDENCE" not in prompt


def test_promptforge_routing_contains_query_plan_fields():
    pf = PromptForge()
    qp = "QUERY_PLAN:\nMODE=LLM_ONLY\nDOMAIN=finance\nNEEDS_RECENCY=false\nTIME_ANCHOR=2022\nEVIDENCE_ENABLED=false\nREASON=historical_time_anchor"
    prompt = pf.build_system_prompt(
        identity_block="id",
        current_time="now",
        memory_context="mem",
        search_context="",
        mode_context="Normal",
        evidence_enabled=False,
        query_plan_summary=qp,
    )
    assert "QUERY_PLAN:" in prompt
    assert "MODE=LLM_ONLY" in prompt
    assert "EVIDENCE_ENABLED=false" in prompt
