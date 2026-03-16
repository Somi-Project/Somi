from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.stacks.ocr_stack import run_ocr_stack


def run(args: dict[str, Any], ctx) -> dict[str, Any]:
    return run_ocr_stack(args)
