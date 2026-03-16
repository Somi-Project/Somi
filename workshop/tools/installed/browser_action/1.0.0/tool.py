from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.browser import BrowserRuntimeError, browser_health, run_browser_flow


def run(args: dict[str, Any], ctx) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    target = str(args.get("target") or "").strip()
    options = dict(args.get("options") or {})

    try:
        if action != "run_flow":
            return {"ok": False, "error": f"Unsupported action: {action}"}
        return run_browser_flow(target, options=options, approved=bool(dict(ctx or {}).get("approved", False)))
    except BrowserRuntimeError as exc:
        return {"ok": False, "error": str(exc), "health": browser_health()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "health": browser_health()}
