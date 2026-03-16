from __future__ import annotations

from typing import Protocol

import numpy as np


class STTProvider(Protocol):
    provider_key: str

    def healthcheck(self) -> dict:
        ...

    def transcribe_final(self, pcm: np.ndarray, sr: int):
        ...
