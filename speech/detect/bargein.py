import numpy as np


class BargeInDetector:
    def __init__(self, threshold: float, consec_frames: int):
        self.threshold = threshold
        self.consec_frames = consec_frames
        self._count = 0

    def process(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        if rms > self.threshold:
            self._count += 1
            if self._count >= self.consec_frames:
                self._count = 0
                return True
        else:
            self._count = 0
        return False
