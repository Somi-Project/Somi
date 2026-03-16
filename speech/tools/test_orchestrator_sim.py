"""Orchestrator simulation audit for streaming/interruptible speech logic."""

from __future__ import annotations

import asyncio

import pytest

np = pytest.importorskip("numpy", reason="numpy unavailable in environment")

import speech.somistate as somistate_mod
from speech.orchestrator import Orchestrator
from speech.somistate import SomiState


class FakeAudioIn:
    def __init__(self, frames):
        self.frames = list(frames)
        self.started = False

    def start(self):
        self.started = True

    def read(self, timeout=0.1):
        if self.frames:
            return self.frames.pop(0)
        return None

    def stop(self):
        pass


class FakeAudioOut:
    def __init__(self):
        self.stop_calls = 0
        self.play_calls = 0

    def play(self, pcm, sr):
        self.play_calls += 1

    def stop(self):
        self.stop_calls += 1


class FakeTTS:
    def synthesize(self, text):
        return np.zeros(800, dtype=np.float32), 8000


class FakeSTT:
    def __init__(self):
        self.calls = 0

    def transcribe_final(self, pcm, sr):
        self.calls += 1
        return "hello there", 0.99


async def _run_test():
    agent_calls = 0

    async def fake_ask_agent_stream(text, user_id):
        nonlocal agent_calls
        agent_calls += 1
        for frag in ["This is", " a response."]:
            await asyncio.sleep(0.01)
            yield frag

    somistate_mod.ask_agent_stream = fake_ask_agent_stream

    speech_frame = np.ones(320, dtype=np.float32) * 0.05
    silence_frame = np.zeros(320, dtype=np.float32)
    loud_frame = np.ones(320, dtype=np.float32) * 0.2
    frames = [speech_frame] * 6 + [silence_frame] * 40 + [loud_frame] * 8

    audio_out = FakeAudioOut()
    state = SomiState(audio_out=audio_out, tts_engine=FakeTTS())
    stt = FakeSTT()
    orch = Orchestrator(audio_in=FakeAudioIn(frames), stt_engine=stt, somistate=state, echo_policy="tier0")

    task = asyncio.create_task(orch.run(user_id="u1"))
    await asyncio.sleep(0.8)

    state.state = state.SPEAKING
    await asyncio.sleep(0.5)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert stt.calls == 1, f"expected exactly 1 STT final call, got {stt.calls}"
    assert agent_calls == 1, f"expected exactly 1 agent call, got {agent_calls}"
    assert audio_out.stop_calls >= 1, "expected barge-in cancel stop() during speaking"


def test_orchestrator_sim():
    asyncio.run(_run_test())
