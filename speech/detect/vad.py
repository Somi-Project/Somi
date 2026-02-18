from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class RMSVAD:
    sample_rate: int
    frame_ms: int
    silence_ms: int
    max_utterance_s: int
    rms_threshold: float
    start_frames: int = 3

    _speech_active: bool = False
    _speech_frames: int = 0
    _silence_frames: int = 0
    _buffer: List[np.ndarray] = field(default_factory=list)

    def process(self, frame: np.ndarray) -> Optional[np.ndarray]:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        silence_limit = max(1, self.silence_ms // self.frame_ms)
        max_frames = int((self.max_utterance_s * 1000) // self.frame_ms)

        if rms > self.rms_threshold:
            self._speech_frames += 1
            self._silence_frames = 0
            if not self._speech_active and self._speech_frames >= self.start_frames:
                self._speech_active = True
            if self._speech_active:
                self._buffer.append(frame)
        elif self._speech_active:
            self._silence_frames += 1
            self._buffer.append(frame)
            if self._silence_frames >= silence_limit:
                return self._finalize()
        else:
            self._speech_frames = 0

        if self._speech_active and len(self._buffer) >= max_frames:
            return self._finalize()
        return None

    def _finalize(self) -> Optional[np.ndarray]:
        if not self._buffer:
            self.reset()
            return None
        out = np.concatenate(self._buffer).astype(np.float32)
        self.reset()
        return out

    def reset(self) -> None:
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._buffer = []
