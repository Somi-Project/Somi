from __future__ import annotations

from typing import Protocol

import numpy as np


class TTSProvider(Protocol):
    provider_key: str

    def healthcheck(self) -> dict:
        ...

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        ...
