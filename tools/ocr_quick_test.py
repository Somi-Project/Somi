from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from handlers.ocr.contracts import OcrRequest
from handlers.ocr.pipeline import run_ocr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="Image path")
    parser.add_argument("--mode", default="auto", choices=["auto", "general", "structured"])
    parser.add_argument("--prompt", default="ocr")
    args = parser.parse_args()

    result = run_ocr(OcrRequest(image_paths=[args.image], mode=args.mode, prompt=args.prompt, source="api"))
    payload = asdict(result)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("exports:", result.exports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
