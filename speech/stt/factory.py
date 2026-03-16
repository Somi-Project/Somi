from __future__ import annotations

from speech.runtime_settings import SpeechRuntimeSettings, load_speech_runtime_settings
from speech.stt.local_whisper import LocalWhisperSTT


def resolve_stt_provider_name(settings: SpeechRuntimeSettings | None = None) -> str:
    runtime = settings or load_speech_runtime_settings()
    requested = str(runtime.stt_provider or "whisper_local").strip().lower()
    if requested == "whisper_local":
        return requested
    return "whisper_local"


def build_stt(settings: SpeechRuntimeSettings | None = None):
    runtime = settings or load_speech_runtime_settings()
    provider = resolve_stt_provider_name(runtime)
    if provider == "whisper_local":
        return LocalWhisperSTT(model_name=runtime.stt_model, expected_sr=runtime.sample_rate)
    raise RuntimeError(f"Unsupported speech STT provider: {provider}")
