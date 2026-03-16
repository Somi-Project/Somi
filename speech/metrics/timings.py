import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from speech.config import METRICS_DIR


@dataclass
class TurnTimings:
    turn_id: int
    created_at: float = field(default_factory=time.perf_counter)
    marks: Dict[str, float] = field(default_factory=dict)

    def mark(self, name: str) -> None:
        self.marks[name] = time.perf_counter()

    def durations_ms(self) -> Dict[str, float]:
        out = {}
        ref = self.created_at
        for key in [
            "vad_finalized",
            "stt_done",
            "agent_done",
            "tts_first_synth_done",
            "first_audio",
            "bargein_stop",
        ]:
            if key in self.marks:
                out[key] = (self.marks[key] - ref) * 1000.0
        return out


class MetricsWriter:
    def __init__(self) -> None:
        os.makedirs(METRICS_DIR, exist_ok=True)
        ts = int(time.time())
        self.path = os.path.join(METRICS_DIR, f"run_{ts}.jsonl")

    def write_turn(self, turn: TurnTimings, extra: Optional[Dict] = None) -> None:
        payload = {
            "turn_id": turn.turn_id,
            "ts": time.time(),
            "durations_ms": turn.durations_ms(),
        }
        if extra:
            payload.update(extra)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
