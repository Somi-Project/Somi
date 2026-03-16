from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.browser import BrowserRuntimeError, browser_health, capture_page_state, capture_screenshot


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()
    target = str(args.get("target") or "").strip()
    options = dict(args.get("options") or {})

    try:
        if action == "health":
            return browser_health()
        if action in {"snapshot", "page_state"}:
            return capture_page_state(target, options=options)
        if action == "screenshot":
            return capture_screenshot(target, options=options)
        return {"ok": False, "error": f"Unsupported action: {action}"}
    except BrowserRuntimeError as exc:
        return {"ok": False, "error": str(exc), "health": browser_health()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "health": browser_health()}
