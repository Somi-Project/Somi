from __future__ import annotations

import pytest

from runtime.ticketing import ExecutionTicket


def test_pending_ticket_persist_load_clear(tmp_path, monkeypatch):
    pytest.importorskip("ollama")
    from agents import Agent

    monkeypatch.chdir(tmp_path)
    a = Agent(name="Somi", user_id="u1")
    t = ExecutionTicket(job_id="j1", action="execute", commands=[["echo", "ok"]], cwd=".")

    a._persist_pending_ticket("u1", t)
    loaded = a._load_pending_ticket("u1")
    assert loaded is not None
    assert loaded.job_id == "j1"
    assert loaded.commands == [["echo", "ok"]]

    a._clear_pending_ticket("u1")
    assert a._load_pending_ticket("u1") is None
