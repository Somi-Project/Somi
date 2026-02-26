from speech.config import TTS_BACKEND
from speech.tts.tts_pocket import PocketTTS
from speech.tts.tts_pocket_server import PocketTTSServerTTS


def build_tts():
    if TTS_BACKEND == "pocket_server":
        return PocketTTSServerTTS()
    if TTS_BACKEND == "pocket":
        return PocketTTS()
    raise RuntimeError(f"Unsupported TTS_BACKEND={TTS_BACKEND!r}")
