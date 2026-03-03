from promptforge import PromptForge


def test_promptforge_omits_evidence_when_disabled():
    pf = PromptForge()
    prompt = pf.build_system_prompt(
        identity_block="id",
        current_time="now",
        memory_context="mem",
        search_context="EVIDENCE (top N=5):\n1) x",
        mode_context="Normal",
        evidence_enabled=False,
        query_plan_summary="QUERY_PLAN:\n- MODE: LLM_ONLY\n- NEEDS_RECENCY: false\n- TIME_ANCHOR: 2022\n- DOMAIN: finance\n- EVIDENCE_ENABLED: false\n- REASON: historical_year_detected",
    )
    assert "## EVIDENCE" not in prompt


def test_promptforge_routing_contains_query_plan_fields():
    pf = PromptForge()
    qp = "QUERY_PLAN:\n- MODE: LLM_ONLY\n- NEEDS_RECENCY: false\n- TIME_ANCHOR: 2022\n- DOMAIN: finance\n- EVIDENCE_ENABLED: false\n- REASON: historical_year_detected"
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
    assert "- MODE: LLM_ONLY" in prompt
    assert "- EVIDENCE_ENABLED: false" in prompt


def test_audit_and_repair_cycle_repeated_three_times_is_stable():
    pf = PromptForge()
    qp = "QUERY_PLAN:\n- MODE: LLM_ONLY\n- NEEDS_RECENCY: false\n- TIME_ANCHOR: 2022\n- DOMAIN: finance\n- EVIDENCE_ENABLED: false\n- REASON: historical_year_detected"
    for _ in range(3):
        prompt = pf.build_system_prompt(
            identity_block="id",
            current_time="now",
            memory_context="mem",
            search_context="EVIDENCE (top N=5):\n1) x",
            mode_context="Normal",
            evidence_enabled=False,
            query_plan_summary=qp,
        )
        assert "## EVIDENCE" not in prompt
        assert "QUERY_PLAN:" in prompt
