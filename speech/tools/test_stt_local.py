from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import soundfile as sf

from speech.stt.factory import build_stt
from speech.tts.factory import build_tts


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the local STT stack.")
    parser.add_argument("--text", default="Testing one two three from Somi.")
    parser.add_argument("--wav-path", default="")
    parser.add_argument("--roundtrip", action="store_true")
    args = parser.parse_args()

    stt = build_stt()
    result_text = ""
    lang_prob = None

    if args.wav_path:
        result_text, lang_prob = stt.transcribe_file(args.wav_path)
        report = {
            "mode": "file",
            "provider": getattr(stt, "provider_key", type(stt).__name__),
            "transcript": result_text,
            "language_probability": lang_prob,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if args.roundtrip:
        tts = build_tts()
        pcm, sr = tts.synthesize(args.text)
        with tempfile.TemporaryDirectory(prefix="somi_stt_") as temp_dir:
            wav_path = Path(temp_dir) / "roundtrip.wav"
            sf.write(str(wav_path), pcm, sr)
            result_text, lang_prob = stt.transcribe_file(str(wav_path))
        report = {
            "mode": "roundtrip",
            "tts_provider": getattr(tts, "provider_key", type(tts).__name__),
            "tts_active_provider": getattr(tts, "active_provider_key", getattr(tts, "provider_key", type(tts).__name__)),
            "stt_provider": getattr(stt, "provider_key", type(stt).__name__),
            "input_text": args.text,
            "transcript": result_text,
            "language_probability": lang_prob,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    raise SystemExit("Pass --wav-path or --roundtrip")


if __name__ == "__main__":
    main()
