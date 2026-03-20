from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from gateway.service import GatewayService
from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.control_plane import OpsControlPlane
from ops.support_bundle import build_support_bundle, write_support_bundle
from runtime.background_tasks import BackgroundTaskStore
from runtime.task_graph import save_task_graph
from runtime.task_resume import build_resume_ledger
from state import SessionEventStore
from workshop.integrations.telegram_runtime import TelegramRuntimeBridge


class TaskContinuityPhase151Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_task_continuity_phase151_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / ".venv").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture" / "TRUST_BOUNDARIES.md").write_text("# Trust\n", encoding="utf-8")
        checkpoint = self.temp_dir / "audit" / "backups" / "phase151_demo_checkpoint"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "update.md").write_text("# Update\n", encoding="utf-8")
        (checkpoint / "phase_upgrade.md").write_text("# Phase\n", encoding="utf-8")
        self.state_store = SessionEventStore(db_path=self.temp_dir / "sessions" / "state" / "system_state.sqlite3")
        self.gateway = GatewayService(root_dir=self.temp_dir / "gateway")
        self.ops = OpsControlPlane(root_dir=self.temp_dir / "sessions" / "ops")
        self.background_store = BackgroundTaskStore(root_dir=self.temp_dir / "sessions" / "ops" / "background_tasks")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_sessions_and_tasks(self) -> None:
        older = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        newer = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        trace_open = self.state_store.start_turn(
            user_id="resume-user",
            thread_id="thr_open_work",
            user_text="Build the continuity ledger",
            routing_prompt="Build the continuity ledger",
            metadata={"surface": "gui", "conversation_id": "desktop-main"},
            created_at=older,
        )
        self.state_store.finish_turn(
            trace=trace_open,
            assistant_text="I started the continuity plan.",
            status="completed",
            route="coding_mode",
            model_name="test-model",
            routing_prompt="Build the continuity ledger",
            latency_ms=10,
            completed_at=older,
        )
        save_task_graph(
            "resume-user",
            "thr_open_work",
            {
                "tasks": [
                    {
                        "task_id": "task_resume_1",
                        "title": "Add a shared resume ledger",
                        "status": "in_progress",
                        "deps": [],
                        "priority": 2,
                        "source": "conversation",
                        "updated_at": older,
                    }
                ],
                "subagents": [],
            },
            root_dir=self.temp_dir / "sessions" / "task_graph",
        )

        trace_recent = self.state_store.start_turn(
            user_id="resume-user",
            thread_id="thr_recent_chat",
            user_text="Tell me a joke",
            routing_prompt="Tell me a joke",
            metadata={"surface": "telegram", "conversation_id": "tg:dm"},
            created_at=newer,
        )
        self.state_store.finish_turn(
            trace=trace_recent,
            assistant_text="Here is a joke.",
            status="completed",
            route="llm_only",
            model_name="test-model",
            routing_prompt="Tell me a joke",
            latency_ms=8,
            completed_at=newer,
        )

        task = self.background_store.create_task(
            user_id="resume-user",
            objective="Continue synthesizing the continuity handoff",
            task_type="research",
            surface="telegram",
            thread_id="thr_open_work",
            max_retries=2,
        )
        self.background_store.heartbeat(
            str(task.get("task_id") or ""),
            summary="Preparing a handoff for the GUI and Telegram surfaces",
            meta={"surface": "telegram"},
        )

    def test_build_resume_ledger_merges_tasks_background_and_surfaces(self) -> None:
        self._seed_sessions_and_tasks()
        sessions = self.state_store.list_sessions(user_id="resume-user", limit=12)
        graphs = {
            "thr_open_work": {"tasks": [{"title": "Add a shared resume ledger", "status": "in_progress"}]},
            "thr_recent_chat": {"tasks": []},
        }
        ledger = build_resume_ledger(
            sessions=sessions,
            background_snapshot=self.background_store.snapshot(user_id="resume-user", limit=12),
            task_graphs=graphs,
            active_thread_id="thr_recent_chat",
        )

        self.assertEqual(int(ledger.get("entry_count") or 0), 2)
        self.assertEqual(str(list(ledger.get("entries") or [])[0].get("thread_id") or ""), "thr_open_work")
        self.assertGreaterEqual(int(list(ledger.get("entries") or [])[0].get("background_count") or 0), 1)
        self.assertTrue(bool(list(ledger.get("entries") or [])[0].get("cross_surface")))
        self.assertEqual(str(list(ledger.get("entries") or [])[0].get("recommended_surface") or ""), "gui")

    def test_control_room_continuity_rows_surface_resume_ledger(self) -> None:
        self._seed_sessions_and_tasks()

        class _StubOntology:
            def __init__(self) -> None:
                self.store = Mock()
                self.store.list_objects.return_value = []

            def refresh_thread(self, **kwargs):
                return None

            def list_actions(self, **kwargs):
                return []

        builder = ControlRoomSnapshotBuilder(
            state_store=self.state_store,
            ontology=_StubOntology(),
            memory_manager=Mock(),
            automation_engine=Mock(),
            automation_store=Mock(),
            delivery_gateway=Mock(),
            tool_registry=Mock(),
            subagent_registry=Mock(),
            subagent_status_store=Mock(),
            workflow_store=Mock(),
            workflow_manifest_store=Mock(),
            ops_control=self.ops,
            jobs_root=self.temp_dir / "jobs",
            artifacts_root=self.temp_dir / "sessions" / "artifacts",
        )
        sessions = self.state_store.list_sessions(user_id="resume-user", limit=12)
        continuity_rows = builder._continuity_rows(
            user_id="resume-user",
            active_thread_id="thr_recent_chat",
            sessions=sessions,
            background_snapshot=self.background_store.snapshot(user_id="resume-user", limit=12),
        )
        row_ids = {str(row.get("id") or "") for row in continuity_rows}
        self.assertIn("task_resume_ledger", row_ids)
        self.assertIn("task_resume_entry:1", row_ids)

    def test_support_bundle_includes_continuity_section(self) -> None:
        self._seed_sessions_and_tasks()
        bundle = write_support_bundle(self.temp_dir, label="phase151")
        continuity = dict(bundle.get("continuity") or {})
        self.assertGreaterEqual(int(continuity.get("entry_count") or 0), 1)
        markdown_path = Path(str(dict(bundle.get("paths") or {}).get("markdown") or ""))
        self.assertIn("## Continuity", markdown_path.read_text(encoding="utf-8"))

    def test_telegram_resume_prefers_thread_with_open_tasks(self) -> None:
        self._seed_sessions_and_tasks()
        bridge = TelegramRuntimeBridge(gateway_service=self.gateway, state_store=self.state_store)
        thread_id = bridge.resolve_thread_id(
            user_id="resume-user",
            prompt="continue with that",
            conversation_id="tg:dm",
        )
        self.assertEqual(thread_id, "thr_open_work")

    def test_thread_capsule_summarizes_surface_handoff(self) -> None:
        self._seed_sessions_and_tasks()
        bridge = TelegramRuntimeBridge(gateway_service=self.gateway, state_store=self.state_store)
        capsule = bridge.build_thread_capsule(user_id="resume-user", thread_id="thr_open_work", active_thread_id="thr_recent_chat")
        self.assertEqual(str(capsule.get("thread_id") or ""), "thr_open_work")
        self.assertIn("telegram", list(capsule.get("surface_names") or []))
        self.assertGreaterEqual(int(capsule.get("open_task_count") or 0), 1)
        self.assertGreaterEqual(int(capsule.get("background_count") or 0), 1)
        self.assertEqual(str(capsule.get("recommended_surface") or ""), "gui")
        self.assertTrue(str(capsule.get("resume_hint") or "").strip())


if __name__ == "__main__":
    raise SystemExit(unittest.main())
