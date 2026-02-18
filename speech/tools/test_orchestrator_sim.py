"""Orchestrator simulation audit for freeze/bug-prone logic.

Validates:
- final VAD utterance triggers exactly one STT call and one agent call
- STT is not called while state is SPEAKING (tier0)
- barge-in triggers stop/cancel path
"""

import asyncio

try:
    import numpy as np
except Exception:
    print("orchestrator_sim_skipped: numpy unavailable")
    raise SystemExit(0)

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

    async def fake_ask_agent(text, user_id):
        nonlocal agent_calls
        agent_calls += 1
        await asyncio.sleep(0.01)
        return "This is a response."

    somistate_mod.ask_agent = fake_ask_agent

    speech_frame = np.ones(320, dtype=np.float32) * 0.05
    silence_frame = np.zeros(320, dtype=np.float32)
    loud_frame = np.ones(320, dtype=np.float32) * 0.2
    frames = [speech_frame] * 6 + [silence_frame] * 40 + [loud_frame] * 8

    audio_out = FakeAudioOut()
    state = SomiState(audio_out=audio_out, tts_engine=FakeTTS())
    stt = FakeSTT()
    orch = Orchestrator(audio_in=FakeAudioIn(frames), stt_engine=stt, somistate=state, echo_policy="tier0")

    async def runner():
        await orch.run(user_id="u1")

    task = asyncio.create_task(runner())
    await asyncio.sleep(1.0)

    state.state = state.SPEAKING
    await asyncio.sleep(0.4)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert stt.calls == 1, f"expected exactly 1 STT final call, got {stt.calls}"
    assert agent_calls == 1, f"expected exactly 1 agent call, got {agent_calls}"
    assert audio_out.stop_calls >= 1, "expected barge-in cancel stop() during speaking"
    print("orchestrator_sim_ok")


if __name__ == "__main__":
    asyncio.run(_run_test())
