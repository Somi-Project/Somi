from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from agents import Agent
from agent_methods.history_methods import _run_tool_with_loop_guard
from runtime.tool_loop_detection import ToolLoopConfig, detect_tool_loop, record_tool_call, record_tool_call_outcome


class _DummyRuntime:
    def run(self, tool_name: str, args: dict[str, object], ctx: dict[str, object]) -> dict[str, object]:  # noqa: ARG002
        return {"ok": True, "tool_name": tool_name, "query": args.get("query")}


class _DummyAgent:
    def __init__(self) -> None:
        self.user_id = "loop_user"
        self.toolbox_runtime = _DummyRuntime()
        self._tool_call_history_by_user: dict[str, list[dict[str, object]]] = {}
        self._tool_loop_warning_cache_by_user: dict[str, dict[str, bool]] = {}

    def _tool_loop_config(self) -> ToolLoopConfig:
        return ToolLoopConfig(
            enabled=True,
            history_size=12,
            warning_threshold=2,
            critical_threshold=99,
            global_circuit_breaker_threshold=120,
            detect_generic_repeat=False,
            detect_no_progress=True,
            detect_ping_pong=False,
        )

    def _tool_call_history(self, active_user_id: str) -> list[dict[str, object]]:
        return self._tool_call_history_by_user.setdefault(active_user_id, [])


class ToolLoopWarningPhase168Tests(unittest.TestCase):
    def test_warning_logs_once_per_warning_key(self) -> None:
        agent = _DummyAgent()

        async def _exercise() -> None:
            for _ in range(4):
                await _run_tool_with_loop_guard(
                    agent,
                    tool_name="web.intelligence",
                    args={"query": "repeat"},
                    ctx={"approved": True},
                    active_user_id="loop_user",
                )

        with patch("agent_methods.history_methods.asyncio", asyncio, create=True):
            with patch("agent_methods.history_methods.sanitize_tool_args", side_effect=lambda tool_name, args: dict(args), create=True):
                with patch("agent_methods.history_methods.detect_tool_loop", side_effect=detect_tool_loop, create=True):
                    with patch("agent_methods.history_methods.record_tool_call", side_effect=record_tool_call, create=True):
                        with patch("agent_methods.history_methods.record_tool_call_outcome", side_effect=record_tool_call_outcome, create=True):
                            with patch("agent_methods.history_methods.logger", create=True) as logger_mock:
                                asyncio.run(_exercise())
        self.assertEqual(logger_mock.warning.call_count, 1)

    def test_live_agent_loop_guard_reaches_critical_block(self) -> None:
        agent = Agent("Somi", user_id="loop_guard_live_user")

        def failing_runtime(tool_name: str, args: dict[str, object], ctx: dict[str, object]) -> dict[str, object]:  # noqa: ARG001
            raise RuntimeError("simulated loop failure")

        agent.toolbox_runtime.run = failing_runtime  # type: ignore[assignment]

        async def _exercise() -> dict[str, object]:
            blocked: dict[str, object] = {}
            for _ in range(1, 26):
                try:
                    out = await agent._run_tool_with_loop_guard(
                        tool_name="web.intelligence",
                        args={"query": "repeat"},
                        ctx={"approved": True, "source": "test", "user_id": "loop_guard_live_user"},
                        active_user_id="loop_guard_live_user",
                    )
                except RuntimeError:
                    continue
                if bool((out or {}).get("_loop_blocked")):
                    blocked = out
                    break
            return blocked

        result = asyncio.run(_exercise())
        self.assertTrue(bool(result.get("_loop_blocked")), msg=f"expected critical block, got {result!r}")
        self.assertEqual(str(result.get("_loop_detector") or ""), "no_progress")
        self.assertGreaterEqual(int(result.get("_loop_count") or 0), 20)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
