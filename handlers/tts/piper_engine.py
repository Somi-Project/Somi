from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import numpy as np

from config.settings import PIPER_CONFIG_PATH, PIPER_MODEL_PATH, TTS_STREAM_CHUNK_MS
from handlers.tts.base import TTSEngine
from speech.metrics.log import logger


class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(self, model_path: str = PIPER_MODEL_PATH, config_path: str = PIPER_CONFIG_PATH, stream_chunk_ms: int = TTS_STREAM_CHUNK_MS):
        self.model_path = model_path
        self.config_path = config_path
        self.stream_chunk_ms = max(10, int(stream_chunk_ms))
        self.sample_rate = 22050
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._voice = self._load_voice()

    def _load_voice(self):
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(self.model_path, config_path=self.config_path)
            self.sample_rate = int(getattr(voice.config, "sample_rate", self.sample_rate))
            logger.info("Loaded Piper voice model=%s sr=%s", self.model_path, self.sample_rate)
            return voice
        except Exception as exc:
            raise RuntimeError(f"Failed to load Piper voice model={self.model_path}: {exc}") from exc

    def synthesize_wav(self, text: str) -> tuple[np.ndarray, int]:
        txt = (text or "").strip()
        if not txt:
            return np.zeros(1, dtype=np.float32), self.sample_rate

        # piper-tts python APIs vary by version; support common variants.
        if hasattr(self._voice, "synthesize"):
            raw = self._voice.synthesize(txt)
        elif hasattr(self._voice, "synthesize_stream_raw"):
            raw = b"".join(self._voice.synthesize_stream_raw(txt))
        else:
            raise RuntimeError("Unsupported piper-tts API on PiperVoice")

        if isinstance(raw, tuple) and len(raw) == 2:
            audio, sr = raw
            pcm = np.asarray(audio, dtype=np.float32).reshape(-1)
            return np.clip(pcm, -1.0, 1.0), int(sr)

        if isinstance(raw, (bytes, bytearray)):
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            return pcm.reshape(-1), self.sample_rate

        pcm = np.asarray(raw, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return np.zeros(1, dtype=np.float32), self.sample_rate
        if np.max(np.abs(pcm)) > 1.5:
            pcm = pcm / 32768.0
        return np.clip(pcm, -1.0, 1.0), self.sample_rate

    def synthesize_stream(self, text: str) -> Iterable[np.ndarray]:
        future = self._executor.submit(self.synthesize_wav, text)
        pcm, sr = future.result()
        self.sample_rate = int(sr)
        chunk = max(1, int(sr * self.stream_chunk_ms / 1000))
        for i in range(0, len(pcm), chunk):
            yield pcm[i : i + chunk].astype(np.float32, copy=False)
