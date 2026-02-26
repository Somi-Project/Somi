from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import numpy as np


class TTSEngine(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize_stream(self, text: str) -> Iterable[np.ndarray]:
        ...

    @abstractmethod
    def synthesize_wav(self, text: str) -> tuple[np.ndarray, int]:
        ...
