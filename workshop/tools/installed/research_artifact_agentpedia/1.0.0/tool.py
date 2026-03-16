from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.stacks.research_artifact import run_research_artifact


def run(args: dict[str, Any], ctx) -> dict[str, Any]:
    return run_research_artifact(args)
