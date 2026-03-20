from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from executive.approvals import build_approval_summary
from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.control_plane import OpsControlPlane
from runtime.autonomy_profiles import build_autonomy_budget, evaluate_autonomy_request


class _DummyToolRegistry:
    def list_toolsets(self, include_empty: bool = True):
        return []

    def list_tools(self):
        return []

    def availability(self, item):
        return {"ok": True}


class _StubAutomationStore:
    pass


class _StubOntology:
    pass


class _StubStateStore:
    pass


class _StubMemoryManager:
    pass


class _StubAutomationEngine:
    pass


class _StubDeliveryGateway:
    pass


class _StubSubagentRegistry:
    pass


class _StubSubagentStatusStore:
    pass


class _StubWorkflowStore:
    pass


class _StubWorkflowManifestStore:
    pass


class AutonomyProfilesPhase137Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_autonomy_phase137_"))
        self.ops = OpsControlPlane(root_dir=self.temp_dir / "ops")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_autonomy_request_policy_blocks_high_risk_and_flags_confirmation(self) -> None:
        ask_first = evaluate_autonomy_request(
            "ask_first",
            risk_tier="LOW",
            mutates_state=True,
            background_task=True,
        )
        self.assertTrue(ask_first["allowed"])
        self.assertTrue(ask_first["requires_confirmation"])
        self.assertIn("mutation_requires_confirmation", list(ask_first.get("reasons") or []))
        self.assertIn("background_task_requires_confirmation", list(ask_first.get("reasons") or []))

        constrained = evaluate_autonomy_request("hands_off_safe", risk_tier="MEDIUM")
        self.assertFalse(constrained["allowed"])
        self.assertFalse(constrained["requires_confirmation"])
        self.assertIn("risk_tier_exceeds_profile:MEDIUM", list(constrained.get("reasons") or []))

    def test_autonomy_budget_tracks_load_and_limits_background(self) -> None:
        budget = build_autonomy_budget("balanced", load_level="high")
        self.assertEqual(int(budget.get("max_parallel_tools") or 0), 1)
        self.assertLessEqual(int(budget.get("max_auto_steps") or 0), 4)

        constrained = evaluate_autonomy_request(
            "hands_off_safe",
            risk_tier="LOW",
            background_task=True,
            load_level="high",
            step_index=1,
            requested_parallel_tools=1,
        )
        self.assertTrue(constrained["allowed"])
        self.assertTrue(constrained["requires_confirmation"])
        self.assertIn("background_load_requires_confirmation", list(constrained.get("reasons") or []))

    def test_autonomy_budget_exhaustion_blocks_further_auto_steps(self) -> None:
        exhausted = evaluate_autonomy_request(
            "balanced",
            risk_tier="LOW",
            step_index=4,
            elapsed_seconds=601,
            retry_count=2,
            requested_parallel_tools=3,
        )
        self.assertFalse(exhausted["allowed"])
        reasons = list(exhausted.get("reasons") or [])
        self.assertIn("step_budget_exhausted", reasons)
        self.assertIn("time_budget_exhausted", reasons)
        self.assertIn("retry_budget_exhausted", reasons)
        self.assertIn("parallel_budget_exhausted", reasons)

    def test_ops_control_plane_persists_active_autonomy_profile(self) -> None:
        initial = self.ops.snapshot()
        self.assertEqual(dict(initial.get("active_autonomy_profile") or {}).get("profile_id"), "balanced")

        revision = self.ops.set_active_autonomy_profile(
            "hands_off_safe",
            actor="tester",
            reason="phase137 validation",
        )
        self.assertTrue(revision["applied"])

        updated = self.ops.snapshot()
        self.assertEqual(dict(updated.get("active_autonomy_profile") or {}).get("profile_id"), "hands_off_safe")
        self.assertGreaterEqual(int(updated.get("autonomy_revision_count") or 0), 2)
        self.assertGreaterEqual(len(self.ops.list_autonomy_profiles()), 3)

    def test_approval_summary_and_control_room_surface_autonomy_profile(self) -> None:
        self.ops.set_active_autonomy_profile("hands_off_safe", actor="tester", reason="surface check")
        summary = build_approval_summary(self.ops, limit=6)
        self.assertEqual(summary["active_profile"], "local_workstation")
        self.assertEqual(summary["active_autonomy_profile"], "hands_off_safe")

        builder = ControlRoomSnapshotBuilder(
            state_store=_StubStateStore(),
            ontology=_StubOntology(),
            memory_manager=_StubMemoryManager(),
            automation_engine=_StubAutomationEngine(),
            automation_store=_StubAutomationStore(),
            delivery_gateway=_StubDeliveryGateway(),
            tool_registry=_DummyToolRegistry(),
            subagent_registry=_StubSubagentRegistry(),
            subagent_status_store=_StubSubagentStatusStore(),
            workflow_store=_StubWorkflowStore(),
            workflow_manifest_store=_StubWorkflowManifestStore(),
            ops_control=self.ops,
        )
        rows = builder._config_rows(
            user_id="default_user",
            thread_id="thread-1",
            agent_name="Somi",
            model_snapshot={"DEFAULT_MODEL": "local-model", "MODEL_CAPABILITY_PROFILE": "balanced"},
            ontology_counts={"Task": 2},
            gateway_snapshot=None,
        )
        autonomy_row = next((row for row in rows if row.get("id") == "autonomy_profile"), {})
        self.assertEqual(autonomy_row.get("status"), "hands_off_safe")
        self.assertIn("runtime=local_workstation", str(autonomy_row.get("subtitle") or ""))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
