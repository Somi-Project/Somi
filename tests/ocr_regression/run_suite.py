from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] if "tests/ocr_regression" in __file__ else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from handlers.ocr.contracts import OcrRequest
from handlers.ocr.pipeline import run_ocr


def main() -> int:
    manifest_path = Path("tests/ocr_regression/dataset_manifest.json")
    cases = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = Path("sessions/test_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ocr_regression_{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for case in cases:
            start = time.time()
            record = {"id": case.get("id"), "mode": case.get("mode"), "status": "ok"}
            try:
                req = OcrRequest(
                    image_paths=case.get("images", []),
                    mode=case.get("mode", "auto"),
                    schema_id=case.get("schema_id"),
                    prompt=case.get("prompt", ""),
                    source="api",
                )
                res = run_ocr(req)
                record.update(
                    {
                        "latency_sec": round(time.time() - start, 3),
                        "coverage": res.quality.coverage,
                        "unk_ratio": res.quality.unk_ratio,
                        "parse_failures": res.quality.parse_failures,
                        "score": res.quality.score,
                    }
                )
            except Exception as exc:
                record.update({"status": "error", "error": str(exc), "latency_sec": round(time.time() - start, 3)})
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
