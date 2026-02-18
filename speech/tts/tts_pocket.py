from __future__ import annotations

import numpy as np

from speech.config import TTS_ALLOW_FALLBACK_TONE, TTS_SAMPLE_RATE
from speech.metrics.log import logger


class PocketTTS:
    def __init__(self):
        self._model = None
        self._backend = "uninitialized"
        self._load_model()

    def _load_model(self):
        last_exc = None
        try:
            from pocket_tts import TTSModel

            self._model = TTSModel()
            self._backend = "pocket_tts"
            logger.info("PocketTTS backend=%s model_loaded=%s", self._backend, self._model is not None)
            return
        except Exception as exc:
            last_exc = exc

        try:
            from pockettts import TTSModel

            self._model = TTSModel()
            self._backend = "pockettts"
            logger.info("PocketTTS backend=%s model_loaded=%s", self._backend, self._model is not None)
            return
        except Exception as exc:
            last_exc = exc

        logger.error("PocketTTS backend load failed; backend=none model_loaded=False err=%r", last_exc)
        if not TTS_ALLOW_FALLBACK_TONE:
            raise RuntimeError("PocketTTS backend unavailable and fallback tone disabled") from last_exc

        self._backend = "tone-fallback"
        logger.warning("PocketTTS backend=%s model_loaded=False", self._backend)

    def synthesize(self, text: str):
        text = (text or "").strip()
        if not text:
            return np.zeros(1, dtype=np.float32), TTS_SAMPLE_RATE
        if self._model is not None:
            audio = self._model.synthesize(text)
            if isinstance(audio, tuple) and len(audio) == 2:
                pcm, sr = audio
            else:
                pcm, sr = audio, TTS_SAMPLE_RATE
            pcm = np.asarray(pcm, dtype=np.float32)
            if pcm.ndim > 1:
                if pcm.ndim == 2:
                    channel_axis = 0 if pcm.shape[0] <= pcm.shape[1] else 1
                    pcm = np.mean(pcm, axis=channel_axis)
                else:
                    time_axis = int(np.argmax(pcm.shape))
                    reduce_axes = tuple(i for i in range(pcm.ndim) if i != time_axis)
                    pcm = np.mean(pcm, axis=reduce_axes)
            pcm = pcm.reshape(-1)
            if pcm.size == 0:
                return np.zeros(1, dtype=np.float32), int(sr)
            return pcm, int(sr)

        # fallback: short tone/silence keeps pipeline operational in dev envs
        sr = TTS_SAMPLE_RATE
        duration = max(0.2, min(2.5, 0.03 * len(text)))
        t = np.linspace(0, duration, int(sr * duration), False)
        tone = 0.05 * np.sin(2 * np.pi * 440 * t)
        return tone.astype(np.float32), sr
