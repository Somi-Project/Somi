from __future__ import annotations

import argparse
import time

import numpy as np

from speech.config import AUDIO_GAIN, EXPECTED_STT_SR, FRAME_MS, SAMPLE_RATE
from speech.io.audio_in import AudioIn
from speech.io.audio_out import AudioOut
from speech.stt.stt_whisper import WhisperSTT
from speech.tts.tts_pocket import PocketTTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Speech stack smoke test")
    parser.add_argument("--input-device", type=int, default=None)
    args = parser.parse_args()

    stt = WhisperSTT(expected_sr=EXPECTED_STT_SR)
    tts = PocketTTS()

    print(f"STT backend: {stt._backend}")
    print(f"TTS backend: {tts._backend}, model_loaded={tts._model is not None}")

    audio_in = AudioIn(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, gain=AUDIO_GAIN, device=args.input_device)
    audio_in.start()
    frames = []
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        frame = audio_in.read(timeout=0.05)
        if frame is not None:
            frames.append(frame)
    audio_in.stop()

    if frames:
        pcm = np.concatenate(frames).astype(np.float32)
        rms = float(np.sqrt(np.mean(pcm ** 2)) + 1e-9)
        print(f"Mic RMS stats: samples={pcm.size} rms={rms:.6f} peak={float(np.max(np.abs(pcm))):.6f}")
    else:
        print("Mic RMS stats: no frames captured")

    out = AudioOut()
    pcm, sr = tts.synthesize("Okay.")
    out.play(pcm, sr)
    print(f"TTS playback: samples={len(pcm)} sr={sr}")


if __name__ == "__main__":
    main()
