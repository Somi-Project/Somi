#!/usr/bin/env python3
"""Light chatflow E2E smoke with filler turns to validate summary continuity."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio


def main() -> int:
    try:
        from agents import Agent
    except Exception as e:
        print(f"import error: {e}")
        return 2

    agent = Agent("Somi", user_id="chatflow_e2e")

    async def run():
        await agent.generate_response("My project codename is Atlas. Remember this.", user_id="chatflow_e2e")
        for i in range(18):
            await agent.generate_response(f"filler turn {i}: discuss generic topic", user_id="chatflow_e2e")
        out = await agent.generate_response("What is my project codename?", user_id="chatflow_e2e")
        print(out)

    try:
        asyncio.run(run())
        return 0
    except Exception as e:
        print(f"runtime error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
