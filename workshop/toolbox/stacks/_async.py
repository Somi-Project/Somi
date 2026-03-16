from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine


def run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from sync code, even if an event loop is active."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover
            error["exc"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "exc" in error:
        raise error["exc"]
    return result.get("value")
