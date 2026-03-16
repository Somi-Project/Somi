from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from speech.runtime_settings import SpeechRuntimeSettings, load_speech_runtime_settings


class Pyttsx3TTS:
    provider_key = "pyttsx3"

    def __init__(self, settings: SpeechRuntimeSettings | None = None) -> None:
        self.settings = settings or load_speech_runtime_settings()

    def _voice_id(self, engine) -> str | None:
        hint = str(self.settings.tts_voice_hint or "").strip().lower()
        if not hint:
            return None
        try:
            voices = engine.getProperty("voices") or []
        except Exception:
            return None
        for voice in voices:
            joined = " ".join(
                str(part or "")
                for part in [getattr(voice, "id", ""), getattr(voice, "name", ""), getattr(voice, "languages", "")]
            ).lower()
            if hint in joined:
                return str(getattr(voice, "id", "") or "")
        return None

    def healthcheck(self) -> dict:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            rate = engine.getProperty("rate")
            volume = engine.getProperty("volume")
            try:
                engine.stop()
            except Exception:
                pass
            return {"available": True, "provider": self.provider_key, "voices": len(voices), "rate": rate, "volume": volume}
        except Exception as exc:
            return {"available": False, "provider": self.provider_key, "error": f"{type(exc).__name__}: {exc}"}

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        import pyttsx3
        import soundfile as sf

        payload = str(text or "").strip()
        if not payload:
            return np.zeros(1, dtype=np.float32), int(self.settings.sample_rate or 16000)

        with tempfile.TemporaryDirectory(prefix="somi_tts_") as temp_dir:
            wav_path = Path(temp_dir) / "tts.wav"
            engine = pyttsx3.init()
            engine.setProperty("rate", int(self.settings.tts_rate))
            engine.setProperty("volume", float(self.settings.tts_volume))
            voice_id = self._voice_id(engine)
            if voice_id:
                try:
                    engine.setProperty("voice", voice_id)
                except Exception:
                    pass
            engine.save_to_file(payload, str(wav_path))
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
            data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)

        pcm = np.asarray(data, dtype=np.float32)
        if pcm.ndim == 2:
            pcm = pcm.mean(axis=1)
        pcm = np.clip(pcm.reshape(-1), -1.0, 1.0).astype(np.float32, copy=False)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if 0.0 < peak < 0.2:
            gain = min(12.0, 0.75 / peak)
            pcm = np.clip(pcm * gain, -1.0, 1.0).astype(np.float32, copy=False)
        if pcm.size == 0:
            return np.zeros(1, dtype=np.float32), int(self.settings.sample_rate or 16000)
        return pcm, int(sr)
