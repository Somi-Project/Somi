from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.control_plane import OpsControlPlane
from runtime.background_tasks import BackgroundTaskStore, build_background_resource_budget
from runtime.performance_controller import PerformanceController


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


class BackgroundTasksPhase138Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_background_phase138_"))
        self.store = BackgroundTaskStore(root_dir=self.temp_dir / "background")
        self.ops = OpsControlPlane(root_dir=self.temp_dir / "ops")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_tracks_task_lifecycle_and_artifacts(self) -> None:
        task = self.store.create_task(
            user_id="tester",
            objective="Research local docs in the background",
            task_type="research",
            surface="gui",
            thread_id="thread-1",
            max_retries=2,
        )
        task_id = str(task.get("task_id") or "")
        self.assertEqual(task.get("status"), "queued")

        running = self.store.heartbeat(
            task_id,
            summary="Collecting evidence rows",
            artifacts=[{"kind": "bundle", "path": "sessions/evidence/demo.json"}],
            meta={"round": 1},
        )
        self.assertEqual(running.get("status"), "running")
        self.assertEqual(len(list(running.get("artifacts") or [])), 1)

        completed = self.store.complete_task(
            task_id,
            summary="Background research completed cleanly",
            handoff={"surface": "gui", "reason": "summary_ready"},
        )
        self.assertEqual(completed.get("status"), "completed")
        self.assertEqual(dict(completed.get("handoff") or {}).get("surface"), "gui")

        snapshot = self.store.snapshot(user_id="tester", limit=8)
        self.assertEqual(int(snapshot.get("counts", {}).get("completed", 0)), 1)
        self.assertIn("resource_budget", snapshot)

    def test_recover_stalled_tasks_promotes_retry_then_failure(self) -> None:
        task = self.store.create_task(
            user_id="tester",
            objective="Index repo in the background",
            task_type="coding",
            max_retries=1,
        )
        task_id = str(task.get("task_id") or "")
        running = self.store.heartbeat(task_id, summary="Scanning workspace")
        stale = dict(running)
        stale["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.store._write_task(stale)

        recovered = self.store.recover_stalled_tasks(stale_after_seconds=60)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].get("status"), "retry_ready")
        self.assertEqual(int(recovered[0].get("retry_count") or 0), 1)

        stale_again = dict(self.store.load_task(task_id) or {})
        stale_again["status"] = "running"
        stale_again["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.store._write_task(stale_again)

        recovered_again = self.store.recover_stalled_tasks(stale_after_seconds=60)
        self.assertEqual(len(recovered_again), 1)
        self.assertEqual(recovered_again[0].get("status"), "failed")

    def test_ops_snapshot_and_control_room_surface_background_queue(self) -> None:
        task = self.ops.create_background_task(
            user_id="tester",
            objective="Draft a summary while the user is away",
            task_type="research",
            surface="gui",
        )
        task_id = str(task.get("task_id") or "")
        self.ops.heartbeat_background_task(task_id, summary="Drafting sections")

        snapshot = self.ops.snapshot(event_limit=8, metric_limit=8)
        queue = dict(snapshot.get("background_tasks") or {})
        self.assertEqual(int(queue.get("running_count") or 0), 1)
        self.assertIn("resource_budget", queue)

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
        background_row = next((row for row in rows if row.get("id") == "background_tasks"), {})
        self.assertEqual(background_row.get("status"), "running")
        self.assertIn("running=1", str(background_row.get("subtitle") or ""))

    def test_performance_controller_exposes_background_budget_hint(self) -> None:
        controller = PerformanceController(profile_name="medium")
        for latency in (18000, 16000, 15000, 14000):
            controller.observe_turn(
                latency_ms=latency,
                success=True,
                prompt_chars=1200,
                history_tokens=900,
                model_name="demo-model",
            )
        budget = controller.background_budget_hint()
        self.assertEqual(controller.current_load_level(), "high")
        self.assertEqual(budget["load_level"], "high")
        self.assertLessEqual(int(budget.get("max_concurrent_tasks") or 0), 1)

    def test_resource_budget_helper_respects_critical_load(self) -> None:
        budget = build_background_resource_budget(load_level="critical", memory_gb=16.0, cpu_count=8)
        self.assertEqual(budget["max_concurrent_tasks"], 0)
        self.assertFalse(budget["heavy_task_allowed"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
