from __future__ import annotations

from speech.runtime_settings import SpeechRuntimeSettings, load_speech_runtime_settings
from speech.tts.tts_pocket_server import PocketTTSServerTTS
from speech.tts.tts_pyttsx3 import Pyttsx3TTS
from speech.tts.tts_tone import ToneTTS


class FallbackTTS:
    provider_key = "tts_chain"

    def __init__(self, providers: list) -> None:
        self.providers = list(providers)
        self.active_provider_key = getattr(self.providers[0], "provider_key", "none") if self.providers else "none"

    def healthcheck(self) -> dict:
        rows = []
        available = False
        for provider in self.providers:
            payload = dict(provider.healthcheck() or {})
            payload["provider"] = payload.get("provider") or getattr(provider, "provider_key", type(provider).__name__)
            rows.append(payload)
            available = available or bool(payload.get("available"))
        return {"available": available, "provider": self.provider_key, "providers": rows}

    def synthesize(self, text: str):
        last_error = None
        for provider in self.providers:
            try:
                pcm, sr = provider.synthesize(text)
                self.active_provider_key = getattr(provider, "provider_key", type(provider).__name__)
                return pcm, sr
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError("No TTS provider could synthesize speech") from last_error


def resolve_tts_provider_name(settings: SpeechRuntimeSettings | None = None) -> str:
    runtime = settings or load_speech_runtime_settings()
    requested = str(runtime.tts_provider or "pyttsx3").strip().lower()
    return requested or "pyttsx3"


def _provider_candidates(runtime: SpeechRuntimeSettings) -> list[str]:
    requested = resolve_tts_provider_name(runtime)
    ordered = [requested, "pyttsx3", "pocket_server", "tone"]
    seen: set[str] = set()
    candidates: list[str] = []
    for item in ordered:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(key)
    return candidates


def _build_provider(provider: str, runtime: SpeechRuntimeSettings):
    if provider == "pyttsx3":
        return Pyttsx3TTS(settings=runtime)
    if provider == "pocket_server":
        return PocketTTSServerTTS()
    if provider == "tone":
        return ToneTTS()
    return None


def build_tts(settings: SpeechRuntimeSettings | None = None):
    runtime = settings or load_speech_runtime_settings()
    providers = []
    for provider_name in _provider_candidates(runtime):
        provider = _build_provider(provider_name, runtime)
        if provider is None:
            continue
        health = dict(provider.healthcheck() or {})
        if bool(health.get("available")):
            providers.append(provider)
    if not providers:
        providers.append(ToneTTS())
    elif getattr(providers[-1], "provider_key", "") != "tone":
        providers.append(ToneTTS())
    return FallbackTTS(providers)
