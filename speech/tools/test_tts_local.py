from __future__ import annotations

import argparse
import json
import time

import numpy as np

from speech.io.audio_out import AudioOut
from speech.tts.factory import build_tts


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the local TTS stack.")
    parser.add_argument("--text", default="Hello from Somi local speech testing.")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    provider = build_tts()
    pcm, sr = provider.synthesize(args.text)
    report = {
        "provider": getattr(provider, "provider_key", type(provider).__name__),
        "active_provider": getattr(provider, "active_provider_key", getattr(provider, "provider_key", type(provider).__name__)),
        "samples": int(len(pcm)),
        "sample_rate": int(sr),
        "peak": float(np.max(np.abs(pcm))) if len(pcm) else 0.0,
        "rms": float(np.sqrt(np.mean(np.square(pcm)))) if len(pcm) else 0.0,
    }

    if args.play:
        audio = AudioOut()
        audio.play(pcm, sr)
        time.sleep(min(2.0, max(0.2, len(pcm) / max(sr, 1))))
        audio.stop()
        report["played"] = True

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
