from __future__ import annotations

import asyncio
import time
from typing import Optional

from speech.brain.agent_bridge import ask_agent_stream
from speech.brain.text_clean import clean_tts_text
from speech.config import AGENT_TIMEOUT_S, BACKCHANNEL_AFTER_MS, PLAYBACK_SLEEP_SLICE_MS
from speech.events import SPEAK_CHUNK, TRANSCRIPT_FINAL, TURN_CANCELLED, EventBus, SpeechEvent
from speech.metrics.log import logger
from speech.metrics.timings import MetricsWriter, TurnTimings
from speech.tts.text_chunker import StreamingChunker


class SomiState:
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"

    def __init__(self, audio_out, tts_engine, backchannel_cb=None):
        self.turn_id: int = 0
        self.state: str = self.LISTENING
        self.last_final_transcript: str = ""
        self.last_final_at: float = 0.0
        self.dedupe_window_s: float = 1.5

        self.audio_out = audio_out
        self.tts_engine = tts_engine
        self.backchannel_cb = backchannel_cb

        self.event_bus = EventBus()
        self.cognition_queue = self.event_bus.subscribe()
        self.playback_queue = self.event_bus.subscribe()

        self.agent_task: Optional[asyncio.Task] = None
        self.backchannel_task: Optional[asyncio.Task] = None
        self.pending_chunks_by_turn: dict[int, int] = {}
        self.agent_finished_turns: set[int] = set()

        self.metrics = MetricsWriter()
        self.turn_metrics: dict[int, TurnTimings] = {}

    def allocate_turn_id(self, transcript: str) -> int | None:
        text = (transcript or "").strip()
        now = time.monotonic()
        if not text:
            return None
        if text == self.last_final_transcript and (now - self.last_final_at) < self.dedupe_window_s:
            return None
        self.last_final_transcript = text
        self.last_final_at = now
        self.turn_id += 1
        return self.turn_id

    async def cancel_current_turn(self, reason: str = "cancel") -> int:
        cancelled_tid = self.turn_id
        if cancelled_tid <= 0:
            return cancelled_tid

        await self.event_bus.publish(SpeechEvent(type=TURN_CANCELLED, turn_id=cancelled_tid, payload={"reason": reason}))
        self.turn_id += 1

        await self._stop_runtime(cancelled_tid)
        self._flush_queue(self.cognition_queue)
        self._flush_queue(self.playback_queue)
        self.pending_chunks_by_turn.pop(cancelled_tid, None)
        self.agent_finished_turns.discard(cancelled_tid)

        self.state = self.LISTENING
        return cancelled_tid

    async def _stop_runtime(self, cancelled_tid: int) -> None:
        if self.agent_task and not self.agent_task.done():
            self.agent_task.cancel()
        if self.backchannel_task and not self.backchannel_task.done():
            self.backchannel_task.cancel()
        self.audio_out.stop()

        tm = self.turn_metrics.get(cancelled_tid)
        if tm:
            tm.mark("bargein_stop")
            self._close_turn_metrics(cancelled_tid, extra={"cancelled": True})

    def _flush_queue(self, queue: asyncio.Queue[SpeechEvent]) -> None:
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break

    def _close_turn_metrics(self, tid: int, extra: dict | None = None) -> None:
        tm = self.turn_metrics.pop(tid, None)
        if tm:
            self.metrics.write_turn(tm, extra=extra)

    def _maybe_finish_turn(self, turn_id: int) -> None:
        if turn_id != self.turn_id:
            return
        pending = self.pending_chunks_by_turn.get(turn_id, 0)
        if pending == 0 and turn_id in self.agent_finished_turns:
            self.state = self.LISTENING
            self._close_turn_metrics(turn_id)
            self.pending_chunks_by_turn.pop(turn_id, None)

    async def cognition_loop(self, user_id: str):
        queue = self.cognition_queue
        while True:
            event = await queue.get()
            try:
                if event.type == TURN_CANCELLED:
                    if event.turn_id == self.turn_id:
                        await self._stop_runtime(event.turn_id)
                        self.state = self.LISTENING
                    continue
                if event.type != TRANSCRIPT_FINAL or event.turn_id != self.turn_id:
                    continue

                transcript = event.payload.get("text", "")
                stt_ms = event.payload.get("stt_ms")
                self.state = self.THINKING
                self.pending_chunks_by_turn[event.turn_id] = 0
                self.agent_finished_turns.discard(event.turn_id)

                tm = TurnTimings(turn_id=event.turn_id)
                tm.mark("vad_finalized")
                if stt_ms is not None:
                    tm.marks["stt_done"] = tm.created_at + (stt_ms / 1000.0)
                self.turn_metrics[event.turn_id] = tm

                self.agent_task = asyncio.create_task(
                    self._run_agent(turn_id=event.turn_id, prompt=transcript, user_id=user_id)
                )
            finally:
                queue.task_done()

    async def _run_agent(self, turn_id: int, prompt: str, user_id: str) -> None:
        first_chunk_sent = False

        async def _backchannel_waiter():
            await asyncio.sleep(BACKCHANNEL_AFTER_MS / 1000.0)
            if turn_id != self.turn_id or first_chunk_sent:
                return
            if self.backchannel_cb:
                self.backchannel_cb()

        self.backchannel_task = asyncio.create_task(_backchannel_waiter())
        chunker = StreamingChunker()
        started_at = time.monotonic()

        try:
            async for fragment in ask_agent_stream(prompt, user_id=user_id):
                if turn_id != self.turn_id:
                    return
                if (time.monotonic() - started_at) > AGENT_TIMEOUT_S:
                    raise asyncio.TimeoutError

                cleaned = clean_tts_text(fragment)
                if not cleaned:
                    continue

                for chunk in chunker.feed(cleaned):
                    if turn_id != self.turn_id:
                        return
                    self.pending_chunks_by_turn[turn_id] = self.pending_chunks_by_turn.get(turn_id, 0) + 1
                    await self.event_bus.publish(
                        SpeechEvent(type=SPEAK_CHUNK, turn_id=turn_id, payload={"chunk": chunk})
                    )
                    first_chunk_sent = True
                    tm = self.turn_metrics.get(turn_id)
                    if tm and "agent_done" not in tm.marks:
                        tm.mark("agent_done")

            for chunk in chunker.flush():
                if turn_id != self.turn_id:
                    return
                self.pending_chunks_by_turn[turn_id] = self.pending_chunks_by_turn.get(turn_id, 0) + 1
                await self.event_bus.publish(SpeechEvent(type=SPEAK_CHUNK, turn_id=turn_id, payload={"chunk": chunk}))
                first_chunk_sent = True

            if not first_chunk_sent and turn_id == self.turn_id:
                self.state = self.LISTENING
                self._close_turn_metrics(turn_id, extra={"empty_response": True})
        except asyncio.TimeoutError:
            if turn_id == self.turn_id:
                self.state = self.LISTENING
                self._close_turn_metrics(turn_id, extra={"timeout": True})
                logger.warning("Agent timed out for turn_id=%s", turn_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if turn_id == self.turn_id:
                self.state = self.LISTENING
                self._close_turn_metrics(turn_id, extra={"agent_error": str(exc)})
                logger.exception("Agent task failed for turn_id=%s: %s", turn_id, exc)
        finally:
            if turn_id == self.turn_id:
                self.agent_finished_turns.add(turn_id)
                self._maybe_finish_turn(turn_id)
            if self.backchannel_task and not self.backchannel_task.done():
                self.backchannel_task.cancel()

    async def playback_loop(self):
        queue = self.playback_queue
        while True:
            event = await queue.get()
            try:
                if event.type == TURN_CANCELLED:
                    if event.turn_id == self.turn_id:
                        self.audio_out.stop()
                        self.state = self.LISTENING
                    continue
                if event.type != SPEAK_CHUNK:
                    continue

                tid = event.turn_id
                if tid != self.turn_id:
                    continue

                chunk = (event.payload.get("chunk") or "").strip()
                if not chunk:
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

                remaining = len(pcm) / max(sr, 1)
                sleep_slice = max(PLAYBACK_SLEEP_SLICE_MS / 1000.0, 0.01)
                while remaining > 0:
                    if tid != self.turn_id:
                        self.audio_out.stop()
                        break
                    step = min(sleep_slice, remaining)
                    await asyncio.sleep(step)
                    remaining -= step
            finally:
                if event.type == SPEAK_CHUNK:
                    tid = event.turn_id
                    self.pending_chunks_by_turn[tid] = max(0, self.pending_chunks_by_turn.get(tid, 0) - 1)
                    self._maybe_finish_turn(tid)
                queue.task_done()

    async def on_transcript_final(self, text: str, user_id: str, stt_ms: float | None = None) -> None:
        tid = self.allocate_turn_id(text)
        if tid is None:
            return
        await self.event_bus.publish(
            SpeechEvent(type=TRANSCRIPT_FINAL, turn_id=tid, payload={"text": text, "user_id": user_id, "stt_ms": stt_ms})
        )

    async def playback_consumer(self):
        await self.playback_loop()
