import argparse
import asyncio
import os

import numpy as np

from speech.brain.agent_bridge import init_agent_bridge
from speech.config import AGENT_NAME_DEFAULT, AUDIO_GAIN, ECHO_POLICY, EXPECTED_STT_SR, FRAME_MS, SAMPLE_RATE, TTS_BACKEND, USER_ID_DEFAULT, USE_STUDIES_DEFAULT
from speech.io.audio_in import AudioIn
from speech.metrics.log import logger
from speech.stt.stt_whisper import WhisperSTT
from speech.tts.factory import build_tts


def _ack(audio_out: AudioOut):
    sr = SAMPLE_RATE
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    tone = 0.08 * np.sin(2 * np.pi * 880 * t)
    audio_out.play(tone.astype(np.float32), sr)


async def _main(args):
    if args.tts_backend:
        os.environ["SOMI_TTS_BACKEND"] = args.tts_backend
    init_agent_bridge(agent_name=args.agent_name, use_studies=args.use_studies, user_id=args.user_id)
    audio_out = AudioOut(device=args.output_device, os_profile=args.os_profile)
    state = SomiState(audio_out=audio_out, tts_engine=build_tts(), backchannel_cb=lambda: _ack(audio_out))
    orchestrator = Orchestrator(
        audio_in=AudioIn(
            sample_rate=SAMPLE_RATE,
            frame_ms=FRAME_MS,
            gain=AUDIO_GAIN,
            device=args.input_device,
            os_profile=args.os_profile,
        ),
        stt_engine=WhisperSTT(expected_sr=EXPECTED_STT_SR),
        somistate=state,
        echo_policy=args.echo_policy,
    )

    barge_frames = 0
    audio_in.start()
    logger.info("Realtime speech loop started")
    try:
        while True:
            frame = audio_in.read(timeout=0.1)
            if frame is None:
                await asyncio.sleep(0.001)
                continue

            rms = float(np.sqrt(np.mean(np.asarray(frame, dtype=np.float32) ** 2)) + 1e-9)
            if player.is_playing and rms >= args.barge_rms_threshold:
                barge_frames += 1
                if barge_frames >= args.barge_frames:
                    player.stop()
                    barge_frames = 0
                    logger.info("Playback interrupted by user speech")
            else:
                barge_frames = 0

            utterance = vad.process(frame)
            if utterance is None:
                continue

            try:
                text, lang_prob = stt.transcribe_final(utterance, SAMPLE_RATE)
            except Exception as exc:
                logger.exception("STT failed: %s", exc)
                continue

            text = (text or "").strip()
            if not text:
                continue
            logger.info("STT final: %r (lang_prob=%s)", text, lang_prob)

            try:
                response = await ask_agent(text, user_id=args.user_id)
            except Exception as exc:
                logger.exception("Agent request failed: %s", exc)
                continue

            response = (response or "").strip()
            if not response:
                continue
            logger.info("Agent response chars=%s", len(response))

            try:
                player.play_frames(tts.synthesize_stream(response), getattr(tts, "sample_rate", 22050))
            except Exception as exc:
                logger.exception("TTS/playback failed: %s", exc)
                continue
    finally:
        player.stop()
        audio_in.stop()


def parse_args():
    p = argparse.ArgumentParser(description="Run low-latency speech loop")
    p.add_argument("--agent-name", default=AGENT_NAME_DEFAULT)
    p.add_argument("--user-id", default=USER_ID_DEFAULT)
    p.add_argument("--use-studies", action="store_true", default=USE_STUDIES_DEFAULT)
    p.add_argument("--input-device", default=os.getenv("SOMI_SPEECH_INPUT_DEVICE"))
    p.add_argument("--output-device", default=os.getenv("SOMI_SPEECH_OUTPUT_DEVICE"))
    p.add_argument("--os-profile", choices=["auto", "windows", "mac", "linux"], default=os.getenv("SOMI_SPEECH_OS_PROFILE", "auto"))
    p.add_argument("--tts-backend", choices=["pocket", "pocket_server"], default=os.getenv("SOMI_TTS_BACKEND", TTS_BACKEND))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info("Starting speech with agent=%s user_id=%s os_profile=%s tts_backend=%s", args.agent_name, args.user_id, args.os_profile, args.tts_backend)
    asyncio.run(_main(args))
