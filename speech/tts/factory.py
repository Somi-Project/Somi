import os

from speech.config import TTS_BACKEND
from speech.metrics.log import logger


def build_tts():
    backend = (os.getenv("SOMI_TTS_BACKEND") or TTS_BACKEND).strip()
    if backend == "pocket_server":
        from speech.tts.tts_pocket_server import PocketTTSServerTTS

        logger.info("Selected TTS backend=%s", backend)
        return PocketTTSServerTTS()

    if backend == "pocket":
        from speech.tts.tts_pocket import PocketTTS

        logger.info("Selected TTS backend=%s", backend)
        return PocketTTS()

    raise RuntimeError(f"Unsupported TTS_BACKEND={backend!r}")
