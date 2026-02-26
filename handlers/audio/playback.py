from __future__ import annotations

import threading
from typing import Iterable, Optional

import numpy as np
import sounddevice as sd

from config.settings import AUDIO_OUTPUT_BLOCKSIZE
from speech.io.devices import resolve_device
from speech.metrics.log import logger


class AudioPlayer:
    def __init__(self, device: Optional[int | str] = None, os_profile: str = "auto", blocksize: int = AUDIO_OUTPUT_BLOCKSIZE):
        self.device = device
        self.os_profile = os_profile
        self.blocksize = int(blocksize)
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.is_playing = False
        self._resolved_device = None
        self._preferred_output_sr: Optional[int] = None
        self._stream_sr: Optional[int] = None

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

    def _negotiate_output_sr(self, desired_sr: int) -> int:
        if self._resolved_device is None:
            self._resolved_device = resolve_device(self.device, kind="output", os_profile=self.os_profile)

        if self._preferred_output_sr is not None:
            try:
                sd.check_output_settings(device=self._resolved_device, samplerate=self._preferred_output_sr, channels=1, dtype="float32")
                return self._preferred_output_sr
            except Exception:
                self._preferred_output_sr = None

        try:
            sd.check_output_settings(device=self._resolved_device, samplerate=desired_sr, channels=1, dtype="float32")
            self._preferred_output_sr = desired_sr
            return desired_sr
        except Exception:
            pass

        for candidate in (48000, 44100, 32000, 24000, 22050, 16000):
            try:
                sd.check_output_settings(device=self._resolved_device, samplerate=candidate, channels=1, dtype="float32")
                self._preferred_output_sr = candidate
                logger.warning("Output device does not support %sHz; using %sHz", desired_sr, candidate)
                return candidate
            except Exception:
                continue

        self._preferred_output_sr = desired_sr
        return desired_sr

    def _ensure_stream(self, sr: int) -> None:
        if self._stream is not None and self._stream_sr == sr:
            return

        if self._stream is not None:
            try:
                self._stream.abort()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._stream_sr = None

        self._stream = sd.OutputStream(
            samplerate=int(sr),
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            device=self._resolved_device,
        )
        self._stream.start()
        self._stream_sr = int(sr)

    def play_frames(self, frames_iter: Iterable[np.ndarray], sr: int) -> None:
        self.stop()
        negotiated_sr = self._negotiate_output_sr(int(sr))
        self._ensure_stream(negotiated_sr)

        self._stop_event.clear()
        self.is_playing = True

        def _runner():
            try:
                for frame in frames_iter:
                    if self._stop_event.is_set():
                        break
                    pcm = np.asarray(frame, dtype=np.float32).reshape(-1)
                    if negotiated_sr != int(sr):
                        pcm = self._resample_linear(pcm, int(sr), negotiated_sr)
                    self._stream.write(pcm.reshape(-1, 1))
            except Exception as exc:
                logger.exception("Audio stream playback failed: %s", exc)
            finally:
                self.is_playing = False

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.25)
        self._thread = None
        self.is_playing = False
        if self._stream is not None:
            try:
                self._stream.abort()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._stream_sr = None
