from __future__ import annotations

import numpy as np


class PocketTTS:
    def __init__(self):
        self._model = None
        self._load_model()

    def _load_model(self):
        try:
            from pockettts import TTSModel  # expected backend

            self._model = TTSModel()
            self._backend = "pockettts"
            return
        except Exception:
            pass

        self._backend = "tone-fallback"

    def synthesize(self, text: str):
        text = (text or "").strip()
        if not text:
            return np.zeros(1, dtype=np.float32), 24000
        if self._model is not None:
            audio = self._model.synthesize(text)
            if isinstance(audio, tuple) and len(audio) == 2:
                pcm, sr = audio
            else:
                pcm, sr = audio, 24000
            pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
            return pcm, int(sr)

        # fallback: short tone/silence keeps pipeline operational in dev envs
        sr = 24000
        duration = max(0.2, min(2.5, 0.03 * len(text)))
        t = np.linspace(0, duration, int(sr * duration), False)
        tone = 0.05 * np.sin(2 * np.pi * 440 * t)
        return tone.astype(np.float32), sr
