from __future__ import annotations

from config.settings import TTS_ENGINE
from handlers.tts.base import TTSEngine
from handlers.tts.pyttsx3_engine import Pyttsx3Engine
from speech.metrics.log import logger


def get_tts_engine(settings=None) -> TTSEngine:
    engine_name = str((settings or {}).get("TTS_ENGINE", TTS_ENGINE) if isinstance(settings, dict) else TTS_ENGINE).lower()
    if engine_name == "piper":
        try:
            from handlers.tts.piper_engine import PiperEngine

            return PiperEngine()
        except Exception as exc:
            logger.warning("Piper load failed; falling back to pyttsx3: %s", exc)
            return Pyttsx3Engine()
    return Pyttsx3Engine()
