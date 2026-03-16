from __future__ import annotations

import argparse
import asyncio
import json
import os

import numpy as np

from speech.brain.agent_bridge import init_agent_bridge
from speech.config import (
    AGENT_NAME_DEFAULT,
    ECHO_POLICY,
    FRAME_MS,
    SAMPLE_RATE,
    TTS_BACKEND,
    USER_ID_DEFAULT,
    USE_STUDIES_DEFAULT,
)
from speech.io.audio_in import AudioIn
from speech.io.audio_out import AudioOut
from speech.metrics.log import logger
from speech.orchestrator import Orchestrator
from speech.somistate import SomiState
from speech.doctor import run_speech_doctor
from speech.stt.factory import build_stt
from speech.tts.factory import build_tts


def _ack(audio_out: AudioOut) -> None:
    sr = SAMPLE_RATE
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    tone = 0.08 * np.sin(2 * np.pi * 880 * t)
    audio_out.play(tone.astype(np.float32), sr)


async def _main(args):
    if args.doctor:
        print(json.dumps(run_speech_doctor(), indent=2, ensure_ascii=False))
        return
    if args.tts_backend:
        os.environ["SOMI_SPEECH_TTS_PROVIDER"] = args.tts_backend

    init_agent_bridge(agent_name=args.agent_name, use_studies=args.use_studies, user_id=args.user_id)

    audio_out = AudioOut(device=args.output_device, os_profile=args.os_profile)
    state = SomiState(audio_out=audio_out, tts_engine=build_tts(), backchannel_cb=lambda: _ack(audio_out))
    orchestrator = Orchestrator(
        audio_in=AudioIn(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=args.input_device, os_profile=args.os_profile),
        stt_engine=build_stt(),
        somistate=state,
        echo_policy=args.echo_policy,
    )
    await orchestrator.run(user_id=args.user_id)


def parse_args():
    p = argparse.ArgumentParser(description="Run low-latency speech loop")
    p.add_argument("--agent-name", default=AGENT_NAME_DEFAULT)
    p.add_argument("--user-id", default=USER_ID_DEFAULT)
    p.add_argument("--use-studies", action="store_true", default=USE_STUDIES_DEFAULT)
    p.add_argument("--input-device", default=os.getenv("SOMI_SPEECH_INPUT_DEVICE"))
    p.add_argument("--output-device", default=os.getenv("SOMI_SPEECH_OUTPUT_DEVICE"))
    p.add_argument("--os-profile", choices=["auto", "windows", "mac", "linux"], default=os.getenv("SOMI_SPEECH_OS_PROFILE", "auto"))
    p.add_argument("--tts-backend", choices=["pyttsx3", "pocket_server", "tone"], default=os.getenv("SOMI_SPEECH_TTS_PROVIDER", TTS_BACKEND))
    p.add_argument("--echo-policy", default=os.getenv("SOMI_ECHO_POLICY", ECHO_POLICY))
    p.add_argument("--doctor", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.doctor:
        logger.info(
            "Starting speech with agent=%s user_id=%s os_profile=%s tts_backend=%s",
            args.agent_name,
            args.user_id,
            args.os_profile,
            args.tts_backend,
        )
    asyncio.run(_main(args))
