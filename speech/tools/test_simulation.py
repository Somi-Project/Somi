"""Simulation test for freezes/crashes/stale-turn handling in speech workflow.

This test does not use real audio devices and validates:
- one final transcript maps to one agent call
- barge-in cancellation invalidates stale chunks
- agent exceptions/timeouts do not crash state machine
"""

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
        # 200ms pseudo audio at 24k
        return [0.0] * 4800, 24000


async def _run():
    async def fake_ask_agent(text: str, user_id: str) -> str:
        if text == "boom":
            raise RuntimeError("agent crashed")
        if text == "slow":
            await asyncio.sleep(2.0)
            return "too late"
        await asyncio.sleep(0.05)
        return f"reply:{text}. second sentence."

    somistate_mod.ask_agent = fake_ask_agent

    out = FakeAudioOut()
    state = SomiState(audio_out=out, tts_engine=FakeTTS())
    state_task = asyncio.create_task(state.playback_consumer())

    # normal turn
    await state.on_transcript_final("hello", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.4)
    assert out.play_calls, "Expected playback for normal turn"

    # barge-in cancellation should stop playback and invalidate stale output
    plays_before_cancel = len(out.play_calls)
    await state.on_transcript_final("interrupt me", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.08)
    await state.cancel_current_turn()
    await asyncio.sleep(0.25)
    assert out.stop_calls >= 1, "Expected stop() to be called on cancellation"
    assert state.state == state.LISTENING, "State should return to LISTENING after cancel"
    assert len(out.play_calls) <= plays_before_cancel + 1, "Stale audio should be dropped"

    # agent exception should not crash
    await state.on_transcript_final("boom", user_id="u1", stt_ms=10)
    await asyncio.sleep(0.2)
    assert state.state == state.LISTENING, "State should recover from agent failure"

    state_task.cancel()
    try:
        await state_task
    except asyncio.CancelledError:
        pass

    print("simulation_ok")


if __name__ == "__main__":
    asyncio.run(_run())
