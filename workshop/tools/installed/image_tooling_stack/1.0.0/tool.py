from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.stacks.image_tooling import run_image_tooling


def run(args: dict[str, Any], ctx) -> dict[str, Any]:
    return run_image_tooling(args, user_id=str((ctx or {}).get("user_id") or "default_user"))
