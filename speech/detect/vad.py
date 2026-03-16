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
    preroll_ms: int = 200
    adaptive_threshold: bool = False
    calibration_ms: int = 1000
    calibration_multiplier: float = 3.5

    _speech_active: bool = False
    _speech_frames: int = 0
    _silence_frames: int = 0
    _buffer: List[np.ndarray] = field(default_factory=list)
    _preroll: List[np.ndarray] = field(default_factory=list)
    _calibration_frames: List[float] = field(default_factory=list)

    def process(self, frame: np.ndarray) -> Optional[np.ndarray]:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        silence_limit = max(1, self.silence_ms // self.frame_ms)
        max_frames = int((self.max_utterance_s * 1000) // self.frame_ms)
        preroll_limit = max(1, self.preroll_ms // self.frame_ms)

        self._preroll.append(frame)
        if len(self._preroll) > preroll_limit:
            self._preroll = self._preroll[-preroll_limit:]

        if self.adaptive_threshold and not self._speech_active:
            calibration_target = max(1, self.calibration_ms // self.frame_ms)
            if len(self._calibration_frames) < calibration_target:
                self._calibration_frames.append(rms)
                if len(self._calibration_frames) == calibration_target:
                    noise_floor = float(np.mean(self._calibration_frames))
                    self.rms_threshold = max(self.rms_threshold, noise_floor * self.calibration_multiplier)

        if rms > self.rms_threshold:
            self._speech_frames += 1
            self._silence_frames = 0
            if not self._speech_active and self._speech_frames >= self.start_frames:
                self._speech_active = True
                if self._preroll:
                    self._buffer.extend(self._preroll)
                # current frame is already included via preroll
            elif self._speech_active:
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
        if self._silence_frames > 0 and len(self._buffer) > self._silence_frames:
            trimmed = self._buffer[:-self._silence_frames]
        else:
            trimmed = self._buffer
        if not trimmed:
            self.reset()
            return None
        out = np.concatenate(trimmed).astype(np.float32)
        self.reset()
        return out

    def reset(self) -> None:
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._buffer = []
        self._preroll = []
        self._calibration_frames = []
