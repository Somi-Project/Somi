from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.control_plane import OpsControlPlane
from runtime.skill_apprenticeship import SkillApprenticeshipLedger


class _DummyWorkflowSuggester:
    def generate(self, *, user_id: str | None = None, limit: int = 6):
        return [
            {
                "skill_id": "tokyo_trip_skill",
                "title": "Tokyo Trip Skill",
                "why": "A successful trip-planning workflow can be reused.",
                "recommended_tools": ["search", "planner"],
            }
        ][: max(1, int(limit or 6))]


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


class SkillApprenticeshipPhase139Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_skill_apprentice_phase139_"))
        self.ledger = SkillApprenticeshipLedger(
            root_dir=self.temp_dir / "apprenticeship",
            workflow_suggester=_DummyWorkflowSuggester(),
        )
        self.ops = OpsControlPlane(root_dir=self.temp_dir / "ops")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ledger_promotes_repeated_workflows_into_approval_only_suggestions(self) -> None:
        for idx in range(3):
            self.ledger.record_activity(
                user_id="tester",
                objective="Plan a Tokyo weekend itinerary",
                kind="background:research",
                surface="gui",
                success=idx > 0,
                tools=["search", "planner"],
            )
        suggestions = self.ledger.build_suggestions(user_id="tester", limit=4)
        repeated = next((row for row in suggestions if row.get("kind") == "workflow_repetition"), {})
        self.assertTrue(bool(repeated.get("approval_required")))
        self.assertTrue(bool(repeated.get("draft_ready")))
        self.assertGreaterEqual(int(repeated.get("count") or 0), 3)
        self.assertIn("Tokyo weekend itinerary", str(repeated.get("title") or ""))

        external = next((row for row in suggestions if row.get("kind") == "workflow_success"), {})
        self.assertEqual(external.get("title"), "Tokyo Trip Skill")

    def test_ops_snapshot_and_control_room_surface_skill_apprenticeship(self) -> None:
        for _ in range(2):
            task = self.ops.create_background_task(
                user_id="tester",
                objective="Summarize release notes for Python 3.13",
                task_type="research",
                surface="gui",
            )
            self.ops.complete_background_task(str(task.get("task_id") or ""), summary="Release notes summarized.")

        snapshot = self.ops.snapshot(event_limit=8, metric_limit=8)
        apprenticeship = dict(snapshot.get("skill_apprenticeship") or {})
        self.assertGreaterEqual(int(apprenticeship.get("approval_required_count") or 0), 1)

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
        rows = builder._observability_rows(ops_snapshot=snapshot, release_report=None, freeze_report=None)
        apprentice_row = next((row for row in rows if row.get("id") == "skill_apprenticeship"), {})
        self.assertEqual(apprentice_row.get("status"), "ready")
        self.assertIn("approval_required=", str(apprentice_row.get("subtitle") or ""))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
