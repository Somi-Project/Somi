from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from config import settings as app_settings


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SpeechRuntimeSettings:
    sample_rate: int
    frame_ms: int
    vad_rms_threshold: float
    vad_speech_hangover_ms: int
    vad_min_utterance_ms: int
    barge_in_rms_threshold: float
    barge_in_frames: int
    stt_provider: str
    stt_model: str
    tts_provider: str
    tts_voice_hint: str
    tts_rate: int
    tts_volume: float
    tts_stream_chunk_ms: int
    tts_allow_network_fallback: bool
    pocket_server_url: str
    piper_model_path: str
    piper_config_path: str
    input_device: str
    output_device: str
    os_profile: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["piper_model_exists"] = Path(self.piper_model_path).exists() if self.piper_model_path else False
        payload["piper_config_exists"] = Path(self.piper_config_path).exists() if self.piper_config_path else False
        return payload


def load_speech_runtime_settings() -> SpeechRuntimeSettings:
    return SpeechRuntimeSettings(
        sample_rate=_env_int("SOMI_SPEECH_SAMPLE_RATE", int(getattr(app_settings, "SPEECH_SAMPLE_RATE", 16000))),
        frame_ms=_env_int("SOMI_SPEECH_FRAME_MS", int(getattr(app_settings, "SPEECH_FRAME_MS", 20))),
        vad_rms_threshold=_env_float("SOMI_SPEECH_VAD_RMS_THRESHOLD", float(getattr(app_settings, "VAD_RMS_THRESHOLD", 0.008))),
        vad_speech_hangover_ms=_env_int(
            "SOMI_SPEECH_VAD_SPEECH_HANGOVER_MS",
            int(getattr(app_settings, "VAD_SPEECH_HANGOVER_MS", 400)),
        ),
        vad_min_utterance_ms=_env_int(
            "SOMI_SPEECH_VAD_MIN_UTTERANCE_MS",
            int(getattr(app_settings, "VAD_MIN_UTTERANCE_MS", 180)),
        ),
        barge_in_rms_threshold=_env_float(
            "SOMI_SPEECH_BARGE_IN_RMS_THRESHOLD",
            float(getattr(app_settings, "BARGE_IN_RMS_THRESHOLD", 0.03)),
        ),
        barge_in_frames=_env_int("SOMI_SPEECH_BARGE_IN_FRAMES", int(getattr(app_settings, "BARGE_IN_FRAMES", 3))),
        stt_provider=_env("SOMI_SPEECH_STT_PROVIDER", str(getattr(app_settings, "SPEECH_STT_PROVIDER", "whisper_local"))),
        stt_model=_env("SOMI_SPEECH_STT_MODEL", str(getattr(app_settings, "SPEECH_STT_MODEL", "tiny.en"))),
        tts_provider=_env("SOMI_SPEECH_TTS_PROVIDER", str(getattr(app_settings, "SPEECH_TTS_PROVIDER", "pyttsx3"))),
        tts_voice_hint=_env("SOMI_SPEECH_TTS_VOICE_HINT", str(getattr(app_settings, "SPEECH_TTS_VOICE_HINT", ""))),
        tts_rate=_env_int("SOMI_SPEECH_TTS_RATE", int(getattr(app_settings, "SPEECH_TTS_RATE", 190))),
        tts_volume=_env_float("SOMI_SPEECH_TTS_VOLUME", float(getattr(app_settings, "SPEECH_TTS_VOLUME", 1.0))),
        tts_stream_chunk_ms=_env_int(
            "SOMI_SPEECH_TTS_STREAM_CHUNK_MS",
            int(getattr(app_settings, "TTS_STREAM_CHUNK_MS", 30)),
        ),
        tts_allow_network_fallback=_env_bool(
            "SOMI_SPEECH_TTS_ALLOW_NETWORK_FALLBACK",
            bool(getattr(app_settings, "SPEECH_TTS_ALLOW_NETWORK_FALLBACK", False)),
        ),
        pocket_server_url=_env(
            "SOMI_SPEECH_POCKET_SERVER_URL",
            str(getattr(app_settings, "SPEECH_POCKET_SERVER_URL", "http://127.0.0.1:8001/v1/audio/speech")),
        ),
        piper_model_path=_env("SOMI_SPEECH_PIPER_MODEL_PATH", str(getattr(app_settings, "PIPER_MODEL_PATH", ""))),
        piper_config_path=_env("SOMI_SPEECH_PIPER_CONFIG_PATH", str(getattr(app_settings, "PIPER_CONFIG_PATH", ""))),
        input_device=_env("SOMI_SPEECH_INPUT_DEVICE", ""),
        output_device=_env("SOMI_SPEECH_OUTPUT_DEVICE", ""),
        os_profile=_env("SOMI_SPEECH_OS_PROFILE", "auto"),
    )
