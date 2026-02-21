#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from handlers.routing import decide_route


def main() -> int:
    tests = [
        ("memory doctor", "command", True),
        ("What's my favorite drink now?", "local_memory_intent", True),
        ("Update: my favorite drink is sparkling water, not iced coffee. Remember.", "local_memory_intent", True),
        ("price of NOW stock", "websearch", False),
        ("100 USD to TTD", "conversion_tool", True),
        ("search latest guidelines for rituximab induction", "websearch", False),
    ]

    failed = 0
    for text, expect_route, expect_veto in tests:
        d = decide_route(text, agent_state={})
        ok = d.route == expect_route and bool(d.tool_veto) == bool(expect_veto)
        print(f"{text}\n  -> route={d.route} veto={d.tool_veto} reason={d.reason} {'OK' if ok else 'FAIL'}")
        if not ok:
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
