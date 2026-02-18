import time
import wave

import numpy as np

from speech.tts.tts_pocket import PocketTTS


def _write_wav(path: str, pcm: np.ndarray, sr: int) -> None:
    pcm16 = np.clip(pcm, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm16.tobytes())


def main():
    tts = PocketTTS()
    for idx, text in enumerate(["Okay.", "This is a longer sentence to benchmark chunk stability and synthesis speed."]):
        t0 = time.perf_counter()
        pcm, sr = tts.synthesize(text)
        ms = (time.perf_counter() - t0) * 1000
        out = f"sessions/speech_runs/test_tts_{idx}.wav"
        _write_wav(out, pcm, sr)
        print(f"{text!r} -> {out} ({ms:.1f}ms)")


if __name__ == "__main__":
    main()
