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
