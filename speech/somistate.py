from __future__ import annotations

import asyncio
import time
from typing import Optional, Tuple

from speech.brain.agent_bridge import ask_agent
from speech.brain.text_clean import clean_tts_text
from speech.config import AGENT_TIMEOUT_S, BACKCHANNEL_AFTER_MS, PLAYBACK_SLEEP_SLICE_MS
from speech.metrics.log import logger
from speech.metrics.timings import MetricsWriter, TurnTimings
from speech.tts.text_chunker import chunk_text


class SomiState:
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"

    def __init__(self, audio_out, tts_engine, backchannel_cb=None):
        self.turn_id: int = 0
        self.agent_task: Optional[asyncio.Task] = None
        self.tts_queue: "asyncio.Queue[Tuple[int, str]]" = asyncio.Queue()
        self.state: str = self.LISTENING
        self.last_final_transcript: str = ""
        self.last_final_at: float = 0.0
        self.dedupe_window_s: float = 1.5

        self.audio_out = audio_out
        self.tts_engine = tts_engine
        self.backchannel_cb = backchannel_cb

        self.metrics = MetricsWriter()
        self.turn_metrics: dict[int, TurnTimings] = {}

    def _new_turn(self) -> int:
        self.turn_id += 1
        return self.turn_id

    def _close_turn_metrics(self, tid: int, extra: dict | None = None) -> None:
        tm = self.turn_metrics.pop(tid, None)
        if not tm:
            return
        self.metrics.write_turn(tm, extra=extra)

    async def cancel_current_turn(self) -> int:
        cancelled_tid = self.turn_id
        self.turn_id += 1
        if self.agent_task and not self.agent_task.done():
            self.agent_task.cancel()
        self.audio_out.stop()
        while not self.tts_queue.empty():
            try:
                self.tts_queue.get_nowait()
                self.tts_queue.task_done()
            except asyncio.QueueEmpty:
                break
        tm = self.turn_metrics.get(cancelled_tid)
        if tm:
            tm.mark("bargein_stop")
            self._close_turn_metrics(cancelled_tid, extra={"cancelled": True})
        self.state = self.LISTENING
        return cancelled_tid

    async def on_transcript_final(self, text: str, user_id: str, stt_ms: float | None = None) -> None:
        text = (text or "").strip()
        now = time.monotonic()
        if not text:
            return
        if text == self.last_final_transcript and (now - self.last_final_at) < self.dedupe_window_s:
            return
        self.last_final_transcript = text
        self.last_final_at = now

        tid = self._new_turn()
        self.state = self.THINKING

        tm = TurnTimings(turn_id=tid)
        tm.mark("vad_finalized")
        if stt_ms is not None:
            tm.marks["stt_done"] = tm.created_at + (stt_ms / 1000.0)
        self.turn_metrics[tid] = tm

        async def _backchannel(local_tid: int):
            await asyncio.sleep(BACKCHANNEL_AFTER_MS / 1000)
            if local_tid != self.turn_id or self.state != self.THINKING:
                return
            if self.backchannel_cb:
                try:
                    self.backchannel_cb()
                except Exception as exc:
                    logger.warning("Backchannel callback failed: %s", exc)

        async def _run_agent(local_tid: int, transcript: str):
            try:
                response = await asyncio.wait_for(ask_agent(transcript, user_id=user_id), timeout=AGENT_TIMEOUT_S)
                if local_tid != self.turn_id:
                    return
                self.turn_metrics[local_tid].mark("agent_done")
                cleaned = clean_tts_text(response)
                chunks = chunk_text(cleaned)
                if not chunks:
                    self.state = self.LISTENING
                    self._close_turn_metrics(local_tid, extra={"empty_response": True})
                    return
                for chunk in chunks:
                    if local_tid != self.turn_id:
                        return
                    await self.tts_queue.put((local_tid, chunk))
                self.state = self.SPEAKING
            except asyncio.TimeoutError:
                if local_tid == self.turn_id:
                    logger.warning("Agent timed out for turn_id=%s", local_tid)
                    self.state = self.LISTENING
                    self._close_turn_metrics(local_tid, extra={"timeout": True})
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if local_tid == self.turn_id:
                    logger.exception("Agent task failed for turn_id=%s: %s", local_tid, exc)
                    self.state = self.LISTENING
                    self._close_turn_metrics(local_tid, extra={"agent_error": str(exc)})

        asyncio.create_task(_backchannel(tid))
        self.agent_task = asyncio.create_task(_run_agent(tid, text))

    async def playback_consumer(self):
        while True:
            tid, chunk = await self.tts_queue.get()
            try:
                if tid != self.turn_id:
                    continue
                self.state = self.SPEAKING

                tm = self.turn_metrics.get(tid)
                try:
                    pcm, sr = self.tts_engine.synthesize(chunk)
                except Exception as exc:
                    logger.exception("TTS synthesis failed for turn_id=%s: %s", tid, exc)
                    self._close_turn_metrics(tid, extra={"tts_error": str(exc)})
                    continue

                if tm and "tts_first_synth_done" not in tm.marks:
                    tm.mark("tts_first_synth_done")
                if tid != self.turn_id:
                    continue

                self.audio_out.play(pcm, sr)
                if tm and "first_audio" not in tm.marks:
                    tm.mark("first_audio")

                duration = len(pcm) / max(sr, 1)
                remaining = duration
                sleep_slice = max(PLAYBACK_SLEEP_SLICE_MS / 1000.0, 0.01)
                while remaining > 0:
                    if tid != self.turn_id:
                        break
                    step = min(sleep_slice, remaining)
                    await asyncio.sleep(step)
                    remaining -= step
            finally:
                self.tts_queue.task_done()
                if tid == self.turn_id and self.tts_queue.empty():
                    self.state = self.LISTENING
                    self._close_turn_metrics(tid)

    def mark_bargein_stop(self, turn_id: int | None = None):
        target = self.turn_id if turn_id is None else turn_id
        tm = self.turn_metrics.get(target)
        if tm:
            tm.mark("bargein_stop")
