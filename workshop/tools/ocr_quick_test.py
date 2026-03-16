from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.runtime import InternalToolRuntime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="Image path")
    parser.add_argument("--mode", default="auto", choices=["auto", "general", "structured"])
    parser.add_argument("--prompt", default="ocr")
    args = parser.parse_args()

    runtime = InternalToolRuntime()
    result = runtime.run(
        "ocr.extract",
        {
            "action": "run",
            "mode": args.mode,
            "image_paths": [args.image],
            "options": {"prompt": args.prompt, "source": "api"},
        },
        {"source": "ocr_quick_test", "approved": True},
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("exports:", list((result or {}).get("exports") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
