from typing import Optional

import numpy as np
import sounddevice as sd

from speech.metrics.log import logger


class AudioOut:
    def __init__(self):
        self._current_sr: Optional[int] = None

    def play(self, pcm: np.ndarray, sr: int) -> None:
        self._current_sr = sr
        try:
            sd.play(np.asarray(pcm, dtype="float32"), sr, blocking=False)
        except Exception as exc:
            logger.exception("Audio playback failed: %s", exc)

    def stop(self) -> None:
        try:
            sd.stop()
        except Exception as exc:
            logger.warning("Audio stop failed: %s", exc)
