from __future__ import annotations

import math

import numpy as np


class ToneTTS:
    provider_key = "tone"

    def __init__(self, sample_rate: int = 24000) -> None:
        self.sample_rate = int(sample_rate or 24000)

    def healthcheck(self) -> dict:
        return {"available": True, "provider": self.provider_key}

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        text = str(text or "").strip()
        duration = max(0.18, min(2.2, 0.04 * max(len(text), 1)))
        sr = self.sample_rate
        t = np.linspace(0.0, duration, max(1, int(duration * sr)), endpoint=False)
        sweep = np.sin((2.0 * math.pi * 420.0 * t) + (60.0 * t * t))
        envelope = np.clip(np.linspace(1.0, 0.15, sweep.size, dtype=np.float32), 0.0, 1.0)
        pcm = (0.08 * sweep.astype(np.float32) * envelope).astype(np.float32)
        return pcm, sr
