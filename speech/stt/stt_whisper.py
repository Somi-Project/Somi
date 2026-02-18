from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


class WhisperSTT:
    def __init__(self, model_name: str = "base", expected_sr: int = 16000):
        self.model_name = model_name
        self._backend = None
        self._model = None
        self.expected_sr = expected_sr
        self._init_model()

    def _init_model(self) -> None:
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="auto", compute_type="default")
            self._backend = "faster-whisper"
            return
        except Exception:
            pass

        import whisper

        self._model = whisper.load_model(self.model_name)
        self._backend = "whisper"

    def transcribe_final(self, pcm: np.ndarray, sr: int) -> Tuple[str, Optional[float]]:
        if sr != self.expected_sr:
            raise ValueError(f"WhisperSTT expected sample rate {self.expected_sr}Hz but got {sr}Hz")

        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
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

        # OpenAI whisper supports ndarray input at the target sample rate.
        result = self._model.transcribe(pcm, language="en", fp16=False)
        text = (result.get("text") or "").strip()
        return text, None
