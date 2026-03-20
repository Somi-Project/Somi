from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from runtime.action_policy import classify_action_class, evaluate_action_policy
from workshop.toolbox.runtime import InternalToolRuntime, ToolRuntimeError


class _RegistryStub:
    def __init__(self, entry: dict[str, object], *, availability: dict[str, object] | None = None) -> None:
        self._entry = dict(entry)
        self._availability = dict(availability or {"ok": True, "issues": []})

    def find(self, tool_name: str) -> dict[str, object] | None:
        if str(tool_name or "").strip().lower() == str(self._entry.get("name") or "").strip().lower():
            return dict(self._entry)
        return None

    def availability(self, entry: dict[str, object]) -> dict[str, object]:
        return dict(self._availability)


class ActionPolicyPhase156Tests(unittest.TestCase):
    def test_classify_action_class_detects_external_message(self) -> None:
        entry = {
            "name": "telegram.send",
            "capabilities": ["messaging", "write"],
            "policy": {"read_only": False, "requires_approval": True, "mutates_state": True, "risk_tier": "MEDIUM"},
        }
        self.assertEqual(classify_action_class("telegram.send", entry), "external_message")

    def test_evaluate_action_policy_requires_approval_for_system_change(self) -> None:
        entry = {
            "name": "cli.exec",
            "capabilities": ["cli", "execute"],
            "channels": ["chat"],
            "backends": ["local"],
            "policy": {"read_only": False, "requires_approval": True, "mutates_state": True, "risk_tier": "LOW"},
            "exposure": {"agent": True, "ui": True, "automation": False},
        }
        decision = evaluate_action_policy(
            tool_name="cli.exec",
            entry=entry,
            runtime_ctx={"source": "chat", "approved": False, "active_autonomy_profile": "balanced"},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_reason, "approval_required")
        self.assertEqual(decision.action_class, "system_change")
        self.assertEqual(decision.confirmation_requirement, "typed")
        self.assertTrue(decision.preview_required)
        self.assertTrue(decision.rollback_advised)

    def test_evaluate_action_policy_respects_channel_contract(self) -> None:
        entry = {
            "name": "browser.runtime",
            "capabilities": ["browser", "read"],
            "channels": ["chat", "gui"],
            "backends": ["local"],
            "policy": {"read_only": True, "requires_approval": False, "mutates_state": False, "risk_tier": "LOW"},
            "exposure": {"agent": True, "ui": True, "automation": False},
        }
        decision = evaluate_action_policy(
            tool_name="browser.runtime",
            entry=entry,
            runtime_ctx={"source": "heartbeat", "approved": False},
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.blocked_reason.startswith("channel:"))

    def test_evaluate_action_policy_respects_autonomy_budgets(self) -> None:
        entry = {
            "name": "browser.runtime",
            "capabilities": ["browser", "read"],
            "channels": ["chat", "gui"],
            "backends": ["local"],
            "policy": {"read_only": True, "requires_approval": False, "mutates_state": False, "risk_tier": "LOW"},
            "exposure": {"agent": True, "ui": True, "automation": False},
        }
        decision = evaluate_action_policy(
            tool_name="browser.runtime",
            entry=entry,
            runtime_ctx={
                "source": "chat",
                "approved": False,
                "active_autonomy_profile": "balanced",
                "step_index": 4,
                "elapsed_seconds": 650,
                "retry_count": 2,
                "requested_parallel_tools": 3,
            },
        )
        self.assertFalse(decision.allowed)
        self.assertIn("step_budget_exhausted", str(decision.blocked_reason))

    def test_internal_tool_runtime_surfaces_action_policy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_root = Path(tmp) / "runtime_info_tool" / "1.0.0"
            tool_root.mkdir(parents=True, exist_ok=True)
            (tool_root / "tool.py").write_text(
                textwrap.dedent(
                    """
                    def run(args, ctx):
                        return {"ok": True, "echo": args.get("value", "")}
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            entry = {
                "name": "runtime.info",
                "path": str(tool_root),
                "channels": ["chat", "gui"],
                "backends": ["local"],
                "capabilities": ["read"],
                "toolsets": ["safe-chat"],
                "policy": {"read_only": True, "requires_approval": False, "mutates_state": False, "risk_tier": "LOW"},
                "exposure": {"agent": True, "ui": True, "automation": False},
                "input_schema": {"type": "object", "properties": {"value": {"type": "string"}}, "additionalProperties": False},
            }
            runtime = InternalToolRuntime(registry=_RegistryStub(entry))
            out = runtime.run("runtime.info", {"value": "hello"}, {"source": "chat", "approved": False})
            policy = dict(dict(out.get("_runtime") or {}).get("policy") or {})
            self.assertEqual(policy.get("action_class"), "read")
            self.assertFalse(bool(policy.get("approval_required")))
            self.assertEqual(policy.get("confirmation_requirement"), "single_click")

    def test_internal_tool_runtime_blocks_unapproved_plugin_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_root = Path(tmp) / "skill_install" / "1.0.0"
            tool_root.mkdir(parents=True, exist_ok=True)
            (tool_root / "tool.py").write_text(
                "def run(args, ctx):\n    return {'ok': True, 'installed': True}\n",
                encoding="utf-8",
            )
            entry = {
                "name": "skill.install",
                "path": str(tool_root),
                "channels": ["chat", "gui"],
                "backends": ["local"],
                "capabilities": ["plugin", "install"],
                "toolsets": ["developer"],
                "policy": {"read_only": False, "requires_approval": True, "mutates_state": True, "risk_tier": "LOW"},
                "exposure": {"agent": True, "ui": True, "automation": False},
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            }
            runtime = InternalToolRuntime(registry=_RegistryStub(entry))
            with self.assertRaises(ToolRuntimeError):
                runtime.run("skill.install", {}, {"source": "chat", "approved": False})


if __name__ == "__main__":
    unittest.main()
