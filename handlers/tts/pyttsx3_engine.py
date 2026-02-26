from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Iterable

import numpy as np

from handlers.tts.base import TTSEngine


class Pyttsx3Engine(TTSEngine):
    name = "pyttsx3"

    def __init__(self):
        import pyttsx3

        self._engine = pyttsx3.init()
        self.sample_rate = 22050

    def synthesize_wav(self, text: str) -> tuple[np.ndarray, int]:
        txt = (text or "").strip()
        if not txt:
            return np.zeros(1, dtype=np.float32), self.sample_rate

        with tempfile.TemporaryDirectory() as d:
            wav_path = Path(d) / "tmp.wav"
            self._engine.save_to_file(txt, str(wav_path))
            self._engine.runAndWait()
            with wave.open(str(wav_path), "rb") as wf:
                sr = wf.getframerate()
                data = wf.readframes(wf.getnframes())
            pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            return pcm, int(sr)

    def synthesize_stream(self, text: str) -> Iterable[np.ndarray]:
        pcm, sr = self.synthesize_wav(text)
        self.sample_rate = int(sr)
        chunk = max(1, int(sr * 0.03))
        for i in range(0, len(pcm), chunk):
            yield pcm[i : i + chunk]
