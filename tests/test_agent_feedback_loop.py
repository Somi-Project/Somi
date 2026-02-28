from __future__ import annotations

import pytest


def test_extract_user_correction_phrase():
    pytest.importorskip("ollama")
    from agents import Agent

    a = Agent(name="Somi", user_id="u-corr")
    note, corrected = a._extract_user_correction("No grok i wanted ABCDEFGH instead")
    assert "correction" in note.lower()
    assert "abcdefgh" in corrected


def test_extract_user_correction_empty_tail():
    pytest.importorskip("ollama")
    from agents import Agent

    a = Agent(name="Somi", user_id="u-corr2")
    note, corrected = a._extract_user_correction("that's not what i meant")
    assert note
    assert corrected == ""


def test_extract_user_correction_ignores_plain_no():
    pytest.importorskip("ollama")
    from agents import Agent

    a = Agent(name="Somi", user_id="u-corr3")
    note, corrected = a._extract_user_correction("No")
    assert note == ""
    assert corrected == ""
