from typing import Optional

import numpy as np
import sounddevice as sd

from speech.io.devices import resolve_device
from speech.metrics.log import logger


class AudioOut:
    def __init__(self, device: Optional[int | str] = None, os_profile: str = "auto"):
        self._current_sr: Optional[int] = None
        self.device = device
        self.os_profile = os_profile
        self._resolved_device: Optional[int] = None

    def play(self, pcm: np.ndarray, sr: int) -> None:
        self._current_sr = sr
        try:
            if self._resolved_device is None:
                self._resolved_device = resolve_device(self.device, kind="output", os_profile=self.os_profile)
            sd.play(np.asarray(pcm, dtype="float32"), sr, blocking=False, device=self._resolved_device)
        except Exception as exc:
            logger.exception("Audio playback failed: %s", exc)

    def stop(self) -> None:
        try:
            sd.stop()
        except Exception as exc:
            logger.warning("Audio stop failed: %s", exc)
