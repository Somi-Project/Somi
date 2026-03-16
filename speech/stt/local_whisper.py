from __future__ import annotations

import importlib.util
from typing import Optional, Tuple

import numpy as np


class LocalWhisperSTT:
    provider_key = "whisper_local"

    def __init__(self, model_name: str = "tiny.en", expected_sr: int = 16000):
        self.model_name = model_name
        self._backend = None
        self._model = None
        self.expected_sr = int(expected_sr or 16000)
        self._init_model()

    def _init_model(self) -> None:
        if importlib.util.find_spec("faster_whisper") is not None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="auto", compute_type="default")
            self._backend = "faster-whisper"
            return

        if importlib.util.find_spec("whisper") is not None:
            import whisper

            self._model = whisper.load_model(self.model_name)
            self._backend = "whisper"
            return

        raise RuntimeError("No local Whisper backend is installed. Install faster-whisper or whisper.")

    def healthcheck(self) -> dict:
        return {"available": True, "provider": self.provider_key, "backend": self._backend, "model": self.model_name}

    @staticmethod
    def _resample_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if int(src_sr) == int(dst_sr):
            return np.asarray(pcm, dtype=np.float32).reshape(-1)
        data = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if data.size <= 1:
            return data
        ratio = float(dst_sr) / float(src_sr)
        out_len = max(1, int(round(data.size * ratio)))
        src_x = np.arange(data.size, dtype=np.float32)
        dst_x = np.linspace(0.0, float(data.size - 1), out_len, dtype=np.float32)
        return np.interp(dst_x, src_x, data).astype(np.float32)

    def prepare_pcm(self, pcm: np.ndarray, sr: int) -> np.ndarray:
        data = np.asarray(pcm, dtype=np.float32)
        if data.ndim == 2:
            data = data.mean(axis=1)
        data = data.reshape(-1)
        if int(sr) != self.expected_sr:
            data = self._resample_linear(data, int(sr), self.expected_sr)
        return data.astype(np.float32, copy=False)

    def transcribe_final(self, pcm: np.ndarray, sr: int) -> Tuple[str, Optional[float]]:
        pcm = self.prepare_pcm(pcm, sr)
        if self._backend == "faster-whisper":
            segments, info = self._model.transcribe(
                pcm,
                language="en",
                vad_filter=True,
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            lang_prob = getattr(info, "language_probability", None)
            return text, lang_prob

        result = self._model.transcribe(pcm, language="en", fp16=False)
        return str((result.get("text") or "").strip()), None

    def transcribe_file(self, file_path: str) -> Tuple[str, Optional[float]]:
        import soundfile as sf

        data, sr = sf.read(str(file_path), dtype="float32", always_2d=False)
        return self.transcribe_final(data, int(sr))
