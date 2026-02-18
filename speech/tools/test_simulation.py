"""Simulation test for streaming speech workflow and cancellation safety."""

import asyncio

import speech.somistate as somistate_mod
from speech.somistate import SomiState


class FakeAudioOut:
    def __init__(self):
        self.play_calls = []
        self.stop_calls = 0

    def play(self, pcm, sr):
        self.play_calls.append((len(pcm), sr))

    def stop(self):
        self.stop_calls += 1


class FakeTTS:
    def synthesize(self, text):
        return [0.0] * 4800, 24000


async def _run():
    async def fake_ask_agent_stream(text: str, user_id: str):
        if text == "boom":
            raise RuntimeError("agent crashed")
        if text == "slow":
            await asyncio.sleep(2.0)
            yield "too late"
            return
        for token in ["reply:", text, ". second sentence."]:
            await asyncio.sleep(0.02)
            yield token

    somistate_mod.ask_agent_stream = fake_ask_agent_stream

    out = FakeAudioOut()
    state = SomiState(audio_out=out, tts_engine=FakeTTS())
    playback_task = asyncio.create_task(state.playback_loop())
    cognition_task = asyncio.create_task(state.cognition_loop(user_id="u1"))

    await state.on_transcript_final("hello", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.4)
    assert out.play_calls, "Expected playback for normal turn"

    plays_before_cancel = len(out.play_calls)
    await state.on_transcript_final("interrupt me", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.05)
    await state.cancel_current_turn(reason="barge_in")
    await asyncio.sleep(0.15)
    assert out.stop_calls >= 1, "Expected stop() to be called on cancellation"
    assert state.state == state.LISTENING, "State should return to LISTENING after cancel"
    assert len(out.play_calls) <= plays_before_cancel + 1, "Stale audio should be dropped"

    await state.on_transcript_final("boom", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.2)
    assert state.state == state.LISTENING, "State should recover from agent failure"

    for t in (playback_task, cognition_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    print("simulation_ok")


if __name__ == "__main__":
    asyncio.run(_run())
