from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

if "ollama" not in sys.modules:
    m = types.ModuleType("ollama")

    class _AsyncClientStub:  # pragma: no cover - import shim
        async def chat(self, *args, **kwargs):
            return {"message": {"content": "stub"}}

    m.AsyncClient = _AsyncClientStub
    sys.modules["ollama"] = m

# lightweight import shims for Agent dependencies used in this test module
if "rag" not in sys.modules:
    rag_m = types.ModuleType("rag")

    class _RAGHandler:
        def __init__(self):
            self.texts = []

    rag_m.RAGHandler = _RAGHandler
    sys.modules["rag"] = rag_m

if "handlers.websearch" not in sys.modules:
    ws_m = types.ModuleType("handlers.websearch")

    class _Converter:
        async def convert(self, *args, **kwargs):
            return ""

    class _WebSearchHandler:
        def __init__(self):
            self.converter = _Converter()

        async def search(self, *args, **kwargs):
            return []

        def format_results(self, *args, **kwargs):
            return ""

    ws_m.WebSearchHandler = _WebSearchHandler
    sys.modules["handlers.websearch"] = ws_m

if "handlers.time_handler" not in sys.modules:
    th_m = types.ModuleType("handlers.time_handler")

    class _TimeHandler:
        def __init__(self, *args, **kwargs):
            pass

        def get_system_date_time(self):
            return "2026-02-28T00:00:00+00:00"

    th_m.TimeHandler = _TimeHandler
    sys.modules["handlers.time_handler"] = th_m

if "handlers.wordgame" not in sys.modules:
    wg_m = types.ModuleType("handlers.wordgame")

    class _WordGameHandler:
        def __init__(self, *args, **kwargs):
            pass

        def start_game(self, *args, **kwargs):
            return False

        def clear_game_state(self):
            return None

        def process_game_input(self, *args, **kwargs):
            return ("", False)

    wg_m.WordGameHandler = _WordGameHandler
    sys.modules["handlers.wordgame"] = wg_m

if "handlers.memory" not in sys.modules:
    mem_m = types.ModuleType("handlers.memory")

    class _Memory3Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def build_injected_context(self, *args, **kwargs):
            return ""

        async def memory_doctor(self, *args, **kwargs):
            return "ok"

    mem_m.Memory3Manager = _Memory3Manager
    sys.modules["handlers.memory"] = mem_m

import agents as agents_mod

from agents import Agent
from handlers.continuity import ContinuityResult
from handlers.contracts.base import build_base
from handlers.contracts.intent import ArtifactIntentDecision
from handlers.contracts.store import ArtifactStore
from handlers.routing import RouteDecision
from runtime.ticketing import ExecutionTicket


class _AsyncNoopTimeout:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyLLM:
    async def chat(self, *args, **kwargs):
        return {"message": {"content": "- Ship docs\n- Run tests"}}


@pytest.fixture
def patched_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(agents_mod, "handle_turn", lambda *a, **k: SimpleNamespace(handled=False, requires_approval=False, response_text="", action_package=None))
    monkeypatch.setattr(agents_mod, "handle_skill_command", lambda *a, **k: SimpleNamespace(handled=False, response="", forced_skill_keys=[]))
    monkeypatch.setattr(agents_mod, "decide_route", lambda *a, **k: RouteDecision(route="llm_only", tool_veto=False, reason="test", signals={}))

    ag = Agent("Somi", user_id="u_async_test")
    ag.artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    ag.ollama_client = _DummyLLM()

    monkeypatch.setattr(ag, "_ensure_async_clients_for_current_loop", lambda: None)
    monkeypatch.setattr(ag, "_enqueue_memory_write", lambda **k: None)
    monkeypatch.setattr(ag, "_schedule_background_task", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_memory_ingest_nonblocking", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_should_inject_due_context", lambda *a, **k: False)

    async def _no_route_override(*args, **kwargs):
        return None

    monkeypatch.setattr(ag, "_llm_decide_freshness_route", _no_route_override)

    async def _mem_ctx(*args, **kwargs):
        return ""

    monkeypatch.setattr(ag.memory, "build_injected_context", _mem_ctx)
    monkeypatch.setattr(ag.fact_distiller, "distill_and_write", lambda *a, **k: 0)
    return ag


def test_async_agent_continuity_short_circuit(monkeypatch, patched_agent):
    ag = patched_agent

    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent=None, confidence=0.0, reason="none", trigger_reason={}),
    )

    continuity_art = build_base(
        artifact_type="artifact_continuity",
        inputs={"user_query": "resume", "route": "llm_only"},
        content={
            "thread_id": "thr_short",
            "top_related_artifacts": [],
            "current_state_summary": "Resuming thread thr_short.",
            "suggested_next_steps": ["Continue with the next step."],
            "assumptions": ["No autonomous actions were executed."],
            "questions": [],
            "safety": {"no_autonomy": True, "no_execution": True},
        },
    )
    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=continuity_art, confidence=0.9))

    out = asyncio.run(ag.generate_response("resume same thing", user_id="u_async_test"))
    assert "# Continuity" in out
    assert ag.artifact_store.get_last_by_type("u_async_test", "artifact_continuity") is not None


def test_async_agent_task_state_single_artifact_path(monkeypatch, patched_agent):
    ag = patched_agent

    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent="plan", confidence=0.9, reason="test", trigger_reason={}),
    )
    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=None, confidence=0.0))

    out = asyncio.run(ag.generate_response("what's left on the docs plan?", user_id="u_async_test"))
    assert "# Task State" in out

    ts = ag.artifact_store.get_last_by_type("u_async_test", "task_state")
    plan = ag.artifact_store.get_last_by_type("u_async_test", "plan")
    assert ts is not None
    assert plan is None


def test_async_agent_read_only_bypass_even_with_pending_ticket(monkeypatch, patched_agent):
    ag = patched_agent
    calls = {"n": 0}

    def _handle_turn(*args, **kwargs):
        calls["n"] += 1
        return SimpleNamespace(handled=False, requires_approval=False, response_text="", action_package=None)

    monkeypatch.setattr(agents_mod, "handle_turn", _handle_turn)
    monkeypatch.setattr(agents_mod, "decide_route", lambda *a, **k: RouteDecision(route="llm_only", tool_veto=False, reason="test", signals={"read_only": True, "requires_execution": False}))
    monkeypatch.setattr(ag, "_load_pending_ticket", lambda user_id: ExecutionTicket(job_id="j1", action="execute", commands=[["echo", "ok"]], cwd="."))

    out = asyncio.run(ag.generate_response("just explain this concept", user_id="u_async_test"))
    assert isinstance(out, str)
    assert calls["n"] == 0


def test_async_agent_invalid_persona_temperature_does_not_fail(monkeypatch, patched_agent):
    ag = patched_agent

    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent=None, confidence=0.0, reason="none", trigger_reason={}),
    )
    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=None, confidence=0.0))
    monkeypatch.setattr(ag, "_refresh_profile_and_persona", lambda: ({}, "Name: Somi", {"temperature": "hot"}))

    out = asyncio.run(ag.generate_response("just chat", user_id="u_async_test"))
    assert isinstance(out, str)


def test_refresh_profile_persists_corrected_active_persona(monkeypatch, patched_agent):
    ag = patched_agent
    saved = {"n": 0, "profile": None}

    monkeypatch.setattr(agents_mod, "load_assistant_profile", lambda: {"active_persona_key": "Name: Missing", "proactivity_level": 1, "focus_domains": [], "privacy_mode": "strict", "brief_first_interaction_of_day": False, "last_brief_date": None, "last_heartbeat_at": None})
    monkeypatch.setattr(agents_mod, "load_persona_catalog", lambda: {"Name: Somi": {"role": "assistant", "temperature": 0.7}})

    def _save(profile):
        saved["n"] += 1
        saved["profile"] = dict(profile or {})

    monkeypatch.setattr(agents_mod, "save_assistant_profile", _save)

    profile, key, persona = ag._refresh_profile_and_persona()
    assert key == "Name: Somi"
    assert saved["n"] == 1
    assert saved["profile"]["active_persona_key"] == "Name: Somi"
    assert isinstance(persona, dict)


def test_naturalize_search_output_handles_finance_markers(monkeypatch, patched_agent):
    ag = patched_agent

    class _CleanupLLM:
        async def chat(self, *args, **kwargs):
            return {"message": {"content": "Cleaned friendly answer."}}

    ag.ollama_client = _CleanupLLM()
    monkeypatch.setattr(agents_mod, "INSTRUCT_MODEL", "stub-instruct", raising=False)

    raw = "Meta: category=finance\nyfinance_history\nReply 'expand 1'"
    out = asyncio.run(ag._naturalize_search_output(raw, "what was btc in nov 2022"))
    assert out == "Cleaned friendly answer."


def test_generate_response_finance_followup_early_path_is_naturalized(monkeypatch, patched_agent):
    ag = patched_agent

    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=None, confidence=0.0))
    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent=None, confidence=0.0, reason="none", trigger_reason={}),
    )

    class _FinanceHandler:
        async def search_historical_price(self, *args, **kwargs):
            return [{"symbol": "BTC", "source": "yfinance_history"}]

    ag.websearch.finance_handler = _FinanceHandler()
    ag.websearch.format_results = lambda *_a, **_k: "Meta: category=finance\nyfinance_history\nraw historical dump"

    class _Ctx:
        last_tool_type = "finance"
        last_results = [{"dummy": True}]
        last_query = "whats the price of bitcoin"

    ag.tool_context_store.get = lambda *_a, **_k: _Ctx()

    async def _naturalize(raw_content, original_prompt):
        assert "yfinance_history" in raw_content
        return "Naturalized finance follow-up answer"

    monkeypatch.setattr(ag, "_naturalize_search_output", _naturalize)
    monkeypatch.setattr(agents_mod.asyncio, "timeout", lambda *_a, **_k: _AsyncNoopTimeout(), raising=False)

    out = asyncio.run(ag.generate_response("what was the price in nov 2022", user_id="u_async_test"))
    assert out == "Naturalized finance follow-up answer"


def test_generate_response_news_expand_then_opinion_flow(monkeypatch, patched_agent):
    ag = patched_agent

    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=None, confidence=0.0))
    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent=None, confidence=0.0, reason="none", trigger_reason={}),
    )

    routes = [
        RouteDecision(route="websearch", tool_veto=False, reason="news", signals={}),
        RouteDecision(route="websearch", tool_veto=False, reason="expand", signals={}),
        RouteDecision(route="llm_only", tool_veto=False, reason="opinion", signals={}),
    ]

    def _decide_route(*args, **kwargs):
        return routes.pop(0)

    monkeypatch.setattr(agents_mod, "decide_route", _decide_route)
    monkeypatch.setattr(agents_mod, "INSTRUCT_MODEL", "stub-instruct", raising=False)
    monkeypatch.setattr(agents_mod.asyncio, "timeout", lambda *_a, **_k: _AsyncNoopTimeout(), raising=False)

    class _SeqLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"message": {"content": "## Web/Search Context\nItem 1: Headline"}}
            if self.calls == 2:
                return {"message": {"content": "Naturalized news summary"}}
            if self.calls == 3:
                return {"message": {"content": "Reply 'expand 1'\nMeta: category=news"}}
            if self.calls == 4:
                return {"message": {"content": "Naturalized expanded item one"}}
            return {"message": {"content": "My opinion: this is significant because ..."}}

    ag.ollama_client = _SeqLLM()
    async def _search(*a, **k):
        return [{"title": "news"}]

    ag.websearch.search = _search
    ag.websearch.format_results = lambda *a, **k: "## Web/Search Context\nsource"

    out1 = asyncio.run(ag.generate_response("news today", user_id="u_async_test"))
    out2 = asyncio.run(ag.generate_response("expand on news item one", user_id="u_async_test"))
    out3 = asyncio.run(ag.generate_response("what is your opinion of that news", user_id="u_async_test"))

    assert out1 == "Naturalized news summary"
    assert out2 == "Naturalized expanded item one"
    assert "opinion" in out3.lower()


def test_async_agent_instruct_route_override_to_websearch(monkeypatch, patched_agent):
    ag = patched_agent
    calls = {"n": 0}

    async def _search(*args, **kwargs):
        calls["n"] += 1
        return [{"title": "stub", "url": "https://example.com", "description": "ok"}]

    monkeypatch.setattr(ag, "_llm_decide_freshness_route", lambda *a, **k: asyncio.sleep(0, result="websearch"))
    ag.websearch.search = _search
    ag.websearch.format_results = lambda *a, **k: "## Web/Search Context\nStub result"

    out = asyncio.run(ag.generate_response("tell me latest market move", user_id="u_async_test"))
    assert isinstance(out, str)
    assert calls["n"] == 1


def test_end_to_end_simulation_matrix(monkeypatch, patched_agent):
    """Simulate key user journeys across routing, follow-up resolution, and response paths."""
    ag = patched_agent

    monkeypatch.setattr(agents_mod, "maybe_emit_continuity_artifact", lambda *a, **k: ContinuityResult(artifact=None, confidence=0.0))
    monkeypatch.setattr(
        ag.artifact_detector,
        "detect",
        lambda *a, **k: ArtifactIntentDecision(artifact_intent=None, confidence=0.0, reason="none", trigger_reason={}),
    )

    async def _freshness_route(query: str, current_route: str):
        q = (query or "").lower()
        if "hypertension guidelines 2023" in q:
            return "llm_only"
        if "compare and contrast" in q:
            return "llm_only"
        return current_route

    monkeypatch.setattr(ag, "_llm_decide_freshness_route", _freshness_route)

    def _decide_route(prompt, agent_state=None):
        pl = (prompt or "").lower()
        if any(k in pl for k in ("news", "price", "weather", "hypertension guidelines 2026")):
            return RouteDecision(route="websearch", tool_veto=False, reason="sim", signals={"intent": "general"})
        return RouteDecision(route="llm_only", tool_veto=False, reason="sim", signals={})

    monkeypatch.setattr(agents_mod, "decide_route", _decide_route)

    class _SeqLLM:
        async def chat(self, *args, **kwargs):
            content = ((kwargs.get("messages") or [{}])[-1].get("content") or "")
            if "Raw content to clean" in content:
                return {"message": {"content": "Naturalized summary."}}
            if "compare and contrast" in content.lower():
                return {"message": {"content": "2026 guideline is newer and broader; 2023 is older and narrower."}}
            return {"message": {"content": "General LLM response."}}

    search_queries = []

    class _Finance:
        async def search_historical_price(self, q, context_symbol=None):
            ql = (q or "").lower()
            if "2021" in ql or "historical" in ql:
                return [{"title": "Historical BTC range", "url": "https://fin/hist", "description": "range", "source": "yfinance_history"}]
            return []

    async def _search(q, **kwargs):
        search_queries.append(q)
        ql = (q or "").lower()
        if "summarize this url" in ql and "news/tt1" in ql:
            return [{"title": "Expanded TT news", "url": "https://news/tt1", "description": "details"}]
        if "summarize this url" in ql and "finance/btc" in ql:
            return [{"title": "Expanded BTC quote", "url": "https://finance/btc", "description": "details"}]
        if "news" in ql:
            return [
                {"title": "Flood alert in Trinidad", "url": "https://news/tt1", "description": "headline", "rank": 1},
                {"title": "Energy summit in Tobago", "url": "https://news/tt2", "description": "headline", "rank": 2},
            ]
        if "current price" in ql or "btc" in ql:
            return [{"title": "BTC quote", "url": "https://finance/btc", "description": "BTC 65,000", "rank": 1}]
        if "weather" in ql:
            return [{"title": "POS weather", "url": "https://weather/pos", "description": "rain chance"}]
        if "hypertension guidelines 2026" in ql:
            return [{"title": "Hypertension guidelines 2026", "url": "https://research/htn-2026", "description": "updated guidance"}]
        return [{"title": "Generic", "url": "https://generic", "description": "fallback"}]

    ag.ollama_client = _SeqLLM()
    ag.websearch.search = _search
    ag.websearch.finance_handler = _Finance()
    ag.websearch.format_results = lambda rows: "## Web/Search Context\n" + "\n".join(
        [f"{i+1}. {r.get('title')} - {r.get('url')}" for i, r in enumerate(rows)]
    )

    prompts = [
        "Give me a general response about blood pressure.",
        "what's the current news in trinidad and tobago",
        "Can u expand on 'Flood alert in Trinidad'?",
        "what is the current price of BTC?",
        "Can u expand on 'BTC quote'?",
        "what was btc price in october 2021",
        "weather in port of spain tomorrow",
        "hypertension guidelines 2026",
        "Hypertension guidelines 2023",
        "compare and contrast the two guidelines",
    ]

    outs = []
    for p in prompts:
        outs.append(asyncio.run(ag.generate_response(p, user_id="u_async_test")))

    # broad stability checks
    assert len(outs) == 10
    assert all(isinstance(x, str) and len(x) > 0 for x in outs)

    # follow-up expansion for quoted news and finance result titles
    assert any("summarize this URL: https://news/tt1" in q for q in search_queries)
    assert any("summarize this URL: https://finance/btc" in q for q in search_queries)

    # 2023 + compare should stay in llm-only path under freshness override in this simulation
    assert not any("hypertension guidelines 2023" == q.lower().strip() for q in search_queries)
