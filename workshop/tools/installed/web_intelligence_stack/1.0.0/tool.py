from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.stacks.web_intelligence import run_web_intelligence


def run(args: dict[str, Any], ctx) -> dict[str, Any]:
    return run_web_intelligence(
        query=str(args.get("query") or ""),
        tool_veto=bool(args.get("tool_veto", False)),
        reason=str(args.get("reason") or ""),
        signals=dict(args.get("signals") or {}),
        route_hint=str(args.get("route_hint") or ""),
    )
