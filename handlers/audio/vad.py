from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class SimpleVAD:
    sample_rate: int
    frame_ms: int
    rms_threshold: float
    speech_hangover_ms: int
    min_utterance_ms: int
    _active: bool = False
    _silence_frames: int = 0
    _buf: List[np.ndarray] = field(default_factory=list)

    def process(self, frame: np.ndarray) -> Optional[np.ndarray]:
        rms = float(np.sqrt(np.mean(np.asarray(frame, dtype=np.float32) ** 2)) + 1e-9)
        hangover = max(1, self.speech_hangover_ms // self.frame_ms)
        min_frames = max(1, self.min_utterance_ms // self.frame_ms)

        if rms >= self.rms_threshold:
            self._active = True
            self._silence_frames = 0
            self._buf.append(np.asarray(frame, dtype=np.float32))
            return None

        if self._active:
            self._silence_frames += 1
            self._buf.append(np.asarray(frame, dtype=np.float32))
            if self._silence_frames >= hangover:
                if len(self._buf) >= min_frames:
                    out = np.concatenate(self._buf).astype(np.float32)
                else:
                    out = None
                self._buf = []
                self._active = False
                self._silence_frames = 0
                return out

        return None
