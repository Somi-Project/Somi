from __future__ import annotations

import asyncio
import time

from speech.config import (
    BARGEIN_CONSEC_FRAMES,
    BARGEIN_RMS_THRESHOLD,
    ECHO_POLICY,
    FRAME_MS,
    MAX_UTTERANCE_S,
    SAMPLE_RATE,
    SILENCE_MS,
    VAD_RMS_THRESHOLD,
)
from speech.detect.bargein import BargeInDetector
from speech.detect.echo import stt_allowed
from speech.detect.vad import RMSVAD
from speech.metrics.log import logger


class Orchestrator:
    def __init__(self, audio_in, stt_engine, somistate, echo_policy: str = ECHO_POLICY):
        self.audio_in = audio_in
        self.stt_engine = stt_engine
        self.somistate = somistate
        self.echo_policy = echo_policy

        self.vad = RMSVAD(
            sample_rate=SAMPLE_RATE,
            frame_ms=FRAME_MS,
            silence_ms=SILENCE_MS,
            max_utterance_s=MAX_UTTERANCE_S,
            rms_threshold=VAD_RMS_THRESHOLD,
        )
        self.bargein = BargeInDetector(BARGEIN_RMS_THRESHOLD, BARGEIN_CONSEC_FRAMES)

    async def run(self, user_id: str):
        self.audio_in.start()
        playback_task = asyncio.create_task(self.somistate.playback_consumer())
        logger.info("Speech orchestrator running")

        try:
            while True:
                frame = self.audio_in.read(timeout=0.1)
                if frame is None:
                    await asyncio.sleep(0.005)
                    continue

                if self.somistate.state == self.somistate.SPEAKING:
                    if self.bargein.process(frame):
                        t0 = time.perf_counter()
                        await self.somistate.cancel_current_turn()
                        logger.info("Barge-in detected; playback cancelled in %.2fms", (time.perf_counter() - t0) * 1000)
                    continue

                if not stt_allowed(self.somistate.state, self.echo_policy):
                    continue

                utterance = self.vad.process(frame)
                if utterance is None:
                    continue

                stt_start = time.perf_counter()
                try:
                    text, conf = self.stt_engine.transcribe_final(utterance, SAMPLE_RATE)
                except Exception as exc:
                    logger.exception("STT failed: %s", exc)
                    continue
                stt_ms = (time.perf_counter() - stt_start) * 1000
                logger.info("STT final: %r (conf=%s, %.2fms)", text, conf, stt_ms)

                if not text.strip():
                    continue
                await self.somistate.on_transcript_final(text, user_id=user_id, stt_ms=stt_ms)
        finally:
            self.audio_in.stop()
            playback_task.cancel()
            try:
                await playback_task
            except asyncio.CancelledError:
                pass
            logger.info("Speech orchestrator stopped")
