from __future__ import annotations

import asyncio
import time

from speech.config import (
    BARGEIN_CONSEC_FRAMES,
    BARGEIN_RMS_THRESHOLD,
    ECHO_POLICY,
    FRAME_MS,
    MAX_UTTERANCE_S,
    PREROLL_MS,
    SAMPLE_RATE,
    SILENCE_MS,
    VAD_RMS_THRESHOLD,
)
from speech.detect.bargein import BargeInDetector
from speech.detect.echo import stt_allowed
from speech.detect.vad import RMSVAD
from speech.events import BARGE_IN, TRANSCRIPT_FINAL, SpeechEvent
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
            preroll_ms=PREROLL_MS,
            adaptive_threshold=True,
        )
        self.bargein = BargeInDetector(BARGEIN_RMS_THRESHOLD, BARGEIN_CONSEC_FRAMES)

    async def perception_loop(self, user_id: str):
        while True:
            frame = self.audio_in.read(timeout=0.1)
            if frame is None:
                await asyncio.sleep(0.005)
                continue

            if self.somistate.state == self.somistate.SPEAKING:
                if self.bargein.process(frame):
                    turn_id = self.somistate.turn_id
                    await self.somistate.event_bus.publish(SpeechEvent(type=BARGE_IN, turn_id=turn_id, payload={}))
                    await self.somistate.cancel_current_turn(reason="barge_in")
                    logger.info("Barge-in detected and turn cancelled: turn_id=%s", turn_id)
                continue

            if not stt_allowed(self.somistate.state, self.echo_policy):
                continue

            utterance = self.vad.process(frame)
            if utterance is None:
                continue

            stt_start = time.monotonic()
            try:
                text, lang_prob = self.stt_engine.transcribe_final(utterance, SAMPLE_RATE)
            except Exception as exc:
                logger.exception("STT failed: %s", exc)
                continue

            stt_ms = (time.monotonic() - stt_start) * 1000
            logger.info("STT final: %r (lang_prob=%s, %.2fms)", text, lang_prob, stt_ms)

            tid = self.somistate.allocate_turn_id(text)
            if tid is None:
                continue

            await self.somistate.event_bus.publish(
                SpeechEvent(
                    type=TRANSCRIPT_FINAL,
                    turn_id=tid,
                    payload={"text": text, "user_id": user_id, "stt_ms": stt_ms},
                )
            )

    async def run(self, user_id: str):
        self.audio_in.start()
        logger.info("Speech orchestrator running (vad_threshold=%.4f adaptive=%s)", self.vad.rms_threshold, self.vad.adaptive_threshold)
        try:
            await asyncio.gather(
                self.perception_loop(user_id=user_id),
                self.somistate.cognition_loop(user_id=user_id),
                self.somistate.playback_loop(),
            )
        finally:
            self.audio_in.stop()
            self.somistate.audio_out.stop()
            logger.info("Speech orchestrator stopped")
