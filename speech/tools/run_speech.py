import argparse
import asyncio

import numpy as np

from speech.brain.agent_bridge import init_agent_bridge
from speech.config import AGENT_NAME_DEFAULT, AUDIO_GAIN, ECHO_POLICY, FRAME_MS, SAMPLE_RATE, USER_ID_DEFAULT, USE_STUDIES_DEFAULT
from speech.io.audio_in import AudioIn
from speech.io.audio_out import AudioOut
from speech.metrics.log import logger
from speech.orchestrator import Orchestrator
from speech.somistate import SomiState
from speech.stt.stt_whisper import WhisperSTT
from speech.tts.tts_pocket import PocketTTS


def _ack(audio_out: AudioOut):
    sr = SAMPLE_RATE
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    tone = 0.08 * np.sin(2 * np.pi * 880 * t)
    audio_out.play(tone.astype(np.float32), sr)


async def _main(args):
    init_agent_bridge(agent_name=args.agent_name, use_studies=args.use_studies, user_id=args.user_id)
    audio_out = AudioOut()
    state = SomiState(audio_out=audio_out, tts_engine=PocketTTS(), backchannel_cb=lambda: _ack(audio_out))
    orchestrator = Orchestrator(
        audio_in=AudioIn(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, gain=AUDIO_GAIN, device=args.input_device),
        stt_engine=WhisperSTT(),
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
    p.add_argument("--input-device", type=int, default=None)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info("Starting speech with agent=%s user_id=%s", args.agent_name, args.user_id)
    asyncio.run(_main(args))
