import queue
from typing import Optional

import numpy as np
import sounddevice as sd

from speech.metrics.log import logger


class AudioIn:
    def __init__(self, sample_rate: int, frame_ms: int, gain: float = 1.0, device: Optional[int] = None):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.blocksize = int(sample_rate * frame_ms / 1000)
        self.gain = gain
        self.device = device
        self.frames: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=100)
        self._stream = None
        self._dropped_frames = 0

    def start(self) -> None:
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("InputStream status: %s", status)
            pcm = (indata[:, 0].astype(np.float32) * self.gain).copy()
            try:
                self.frames.put_nowait(pcm)
            except queue.Full:
                self._dropped_frames += 1
                if self._dropped_frames == 1 or self._dropped_frames % 25 == 0:
                    logger.warning("AudioIn queue full; dropping oldest frame (drops=%s, qsize=%s)", self._dropped_frames, self.frames.qsize())
                try:
                    _ = self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(pcm)
                except queue.Full:
                    pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=self.blocksize,
            device=self.device,
        )
        self._stream.start()
        logger.info("Mic capture started")

    def read(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
