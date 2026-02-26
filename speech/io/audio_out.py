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
        self._preferred_output_sr: Optional[int] = None

    @staticmethod
    def _resample_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr:
            return np.asarray(pcm, dtype=np.float32)

        data = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if data.size <= 1:
            return data

        ratio = float(dst_sr) / float(src_sr)
        out_len = max(1, int(round(data.size * ratio)))
        src_x = np.arange(data.size, dtype=np.float32)
        dst_x = np.linspace(0.0, float(data.size - 1), out_len, dtype=np.float32)
        return np.interp(dst_x, src_x, data).astype(np.float32)

    def _resolve_supported_sr(self, pcm: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
        if self._resolved_device is None:
            self._resolved_device = resolve_device(self.device, kind="output", os_profile=self.os_profile)

        if self._preferred_output_sr is not None:
            try:
                sd.check_output_settings(device=self._resolved_device, samplerate=self._preferred_output_sr, channels=1, dtype="float32")
                return self._resample_linear(pcm, sr, self._preferred_output_sr), self._preferred_output_sr
            except Exception:
                self._preferred_output_sr = None

        try:
            sd.check_output_settings(device=self._resolved_device, samplerate=sr, channels=1, dtype="float32")
            self._preferred_output_sr = sr
            return np.asarray(pcm, dtype=np.float32), sr
        except Exception:
            pass

        # Windows hardware commonly supports these even when 24k/22.05k doesn't.
        candidates = [48000, 44100, 32000, 24000, 22050, 16000]
        for candidate_sr in candidates:
            try:
                sd.check_output_settings(device=self._resolved_device, samplerate=candidate_sr, channels=1, dtype="float32")
                self._preferred_output_sr = candidate_sr
                logger.warning("Output device does not support %sHz; resampling playback to %sHz", sr, candidate_sr)
                return self._resample_linear(pcm, sr, candidate_sr), candidate_sr
            except Exception:
                continue

        return np.asarray(pcm, dtype=np.float32), sr

    def play(self, pcm: np.ndarray, sr: int) -> None:
        self._current_sr = sr
        try:
            pcm32, out_sr = self._resolve_supported_sr(pcm, int(sr))
            sd.play(pcm32, out_sr, blocking=False, device=self._resolved_device)
        except Exception as exc:
            logger.exception("Audio playback failed: %s", exc)

    def stop(self) -> None:
        try:
            sd.stop()
        except Exception as exc:
            logger.warning("Audio stop failed: %s", exc)
