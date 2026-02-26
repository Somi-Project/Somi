import argparse
import asyncio
import os

import numpy as np

from speech.brain.agent_bridge import init_agent_bridge
from speech.config import AGENT_NAME_DEFAULT, AUDIO_GAIN, ECHO_POLICY, EXPECTED_STT_SR, FRAME_MS, SAMPLE_RATE, USER_ID_DEFAULT, USE_STUDIES_DEFAULT
from speech.io.audio_in import AudioIn
from speech.io.audio_out import AudioOut
from speech.metrics.log import logger
from speech.orchestrator import Orchestrator
from speech.somistate import SomiState
from speech.stt.stt_whisper import WhisperSTT
from speech.tts.factory import build_tts


def _ack(audio_out: AudioOut):
    sr = SAMPLE_RATE
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    tone = 0.08 * np.sin(2 * np.pi * 880 * t)
    audio_out.play(tone.astype(np.float32), sr)


async def _main(args):
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
    await orchestrator.run(user_id=args.user_id)


def parse_args():
    p = argparse.ArgumentParser(description="Run Somi speech loop")
    p.add_argument("--agent-name", default=AGENT_NAME_DEFAULT)
    p.add_argument("--user-id", default=USER_ID_DEFAULT)
    p.add_argument("--use-studies", action="store_true", default=USE_STUDIES_DEFAULT)
    p.add_argument("--echo-policy", choices=["tier0", "tier1"], default=ECHO_POLICY)
    p.add_argument("--input-device", default=os.getenv("SOMI_SPEECH_INPUT_DEVICE"), help="Input device index or name substring")
    p.add_argument("--output-device", default=os.getenv("SOMI_SPEECH_OUTPUT_DEVICE"), help="Output device index or name substring")
    p.add_argument("--os-profile", choices=["auto", "windows", "mac", "linux"], default=os.getenv("SOMI_SPEECH_OS_PROFILE", "auto"))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info("Starting speech with agent=%s user_id=%s os_profile=%s", args.agent_name, args.user_id, args.os_profile)
    asyncio.run(_main(args))
