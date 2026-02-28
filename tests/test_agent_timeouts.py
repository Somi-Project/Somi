from __future__ import annotations

import pytest


def test_agent_timeout_profiles():
    pytest.importorskip("ollama")
    from agents import Agent

    a = Agent(name="Somi", user_id="u-timeout")

    a.context_profile = "4k"
    assert a._response_timeout_seconds() == 45.0
    assert a._vision_timeout_seconds() == 90.0

    a.context_profile = "16k"
    assert a._response_timeout_seconds() == 120.0
    assert a._vision_timeout_seconds() == 180.0

    a.context_profile = "8k"
    assert a._response_timeout_seconds() == 75.0
    assert a._vision_timeout_seconds() == 120.0
