from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from handlers.audio.playback import AudioPlayer
from handlers.tts import get_tts_engine


def main() -> None:
    out_dir = Path("sessions/test_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"voice_latency_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    t0 = time.perf_counter()
    engine = get_tts_engine()
    cold_load_s = time.perf_counter() - t0

    phrase = "Hello, this is a latency test."
    t1 = time.perf_counter()
    pcm, sr = engine.synthesize_wav(phrase)
    synth_s = time.perf_counter() - t1

    player = AudioPlayer()
    t2 = time.perf_counter()
    player.play_frames(engine.synthesize_stream(phrase), sr)
    first_sound_est_s = time.perf_counter() - t2
    time.sleep(0.2)
    stop_t0 = time.perf_counter()
    player.stop()
    stop_s = time.perf_counter() - stop_t0

    rec = {
        "cold_load_s": cold_load_s,
        "synth_s": synth_s,
        "time_to_first_sound_est_s": first_sound_est_s,
        "stop_latency_s": stop_s,
        "sr": int(sr),
        "samples": int(len(pcm)),
    }
    with out_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
