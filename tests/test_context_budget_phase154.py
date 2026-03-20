from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.context_budget import run_context_budget_status
from ops.doctor import run_somi_doctor
from ops.support_bundle import write_support_bundle
from runtime.history_compaction import COMPACTION_PREFIX
from state import SessionEventStore


ROOT = Path(__file__).resolve().parents[1]


class ContextBudgetPhase154Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_context_budget_phase154_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / ".venv").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture" / "TRUST_BOUNDARIES.md").write_text("# Trust\n", encoding="utf-8")
        checkpoint = self.temp_dir / "audit" / "backups" / "phase154_demo_checkpoint"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "update.md").write_text("# Update\n", encoding="utf-8")
        (checkpoint / "phase_upgrade.md").write_text("# Phase\n", encoding="utf-8")
        self.state_store = SessionEventStore(db_path=self.temp_dir / "sessions" / "state" / "system_state.sqlite3")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_sessions(self) -> None:
        older = datetime.now(timezone.utc) - timedelta(minutes=90)
        for idx in range(14):
            created = (older + timedelta(minutes=idx * 2)).isoformat()
            trace = self.state_store.start_turn(
                user_id="ctx-user",
                thread_id="thr_long",
                user_text=f"Continue the long planning task {idx} " + ("details " * 40),
                routing_prompt="Deep research planning task",
                metadata={"surface": "gui", "conversation_id": "desktop-main"},
                created_at=created,
            )
            self.state_store.finish_turn(
                trace=trace,
                assistant_text=("Working through the long planning task. " + ("evidence " * 45)).strip(),
                status="completed",
                route="deep_browse",
                model_name="test-model",
                routing_prompt="Deep research planning task",
                latency_ms=18,
                completed_at=created,
            )

        compaction_time = datetime.now(timezone.utc).isoformat()
        compact_trace = self.state_store.start_turn(
            user_id="ctx-user",
            thread_id="thr_compacted",
            user_text="Keep going with the repair checklist",
            routing_prompt="Repair checklist",
            metadata={"surface": "telegram", "conversation_id": "tg:dm"},
            created_at=compaction_time,
        )
        self.state_store.finish_turn(
            trace=compact_trace,
            assistant_text=(
                f"{COMPACTION_PREFIX} refreshed 2026-03-19 10:00 UTC\n"
                "- Ledger intent: finish the repair checklist\n"
                "- Ledger open loops: verify the generator wiring\n"
                "- Ledger unresolved asks: confirm which spare parts are still missing"
            ),
            status="completed",
            route="coding_mode",
            model_name="test-model",
            routing_prompt="Repair checklist",
            latency_ms=12,
            completed_at=compaction_time,
        )

    def test_context_budget_reports_pressure_and_compaction(self) -> None:
        self._seed_sessions()
        report = run_context_budget_status(self.temp_dir, user_id="ctx-user", limit=8)

        self.assertEqual(int(report.get("session_count") or 0), 2)
        self.assertEqual(int(report.get("compacted_session_count") or 0), 1)
        self.assertGreaterEqual(int(report.get("pressure_count") or 0), 1)
        self.assertIn(str(list(report.get("entries") or [])[0].get("thread_id") or ""), {"thr_long", "thr_compacted"})

    def test_control_room_includes_context_tab(self) -> None:
        self._seed_sessions()

        class _StubOntology:
            def __init__(self) -> None:
                self.store = Mock()
                self.store.list_objects.return_value = []

            def refresh_thread(self, **kwargs):
                return None

            def list_actions(self, **kwargs):
                return []

        class _StubToolRegistry:
            def list_toolsets(self, include_empty: bool = True):
                return []

            def list_tools(self):
                return []

            def availability(self, item):
                return {"ok": True}

        class _StubDeliveryGateway:
            def list_channels(self):
                return []

            def list_messages(self, channel_name, box="inbox", limit=5):
                return []

        class _StubMemoryStore:
            def latest_by_scope(self, user_id, scope, limit=6):
                return []

            def latest_session_summary(self, user_id):
                return {}

            def pinned_items(self, user_id, limit=8):
                return []

            def recent_events(self, user_id, limit=10):
                return []

            def latest_retrieval_trace(self, user_id):
                return {}

        class _StubFrozenStore:
            def read_snapshot(self, user_id):
                return {}

        class _StubMemoryManager:
            def __init__(self) -> None:
                self.store = _StubMemoryStore()
                self.frozen_store = _StubFrozenStore()
                self.vault = None

            def run_hygiene_check(self, user_id):
                return {"scan_issue_count": 0, "expired_count": 0, "review_status": "idle"}

            def build_preference_graph_sync(self, user_id, limit=12):
                return {"node_count": 0, "summary": "No preference graph yet", "updated_at": ""}

            def build_memory_review_sync(self, user_id, limit=6):
                return {"status": "idle", "summary": "No memory review data yet", "alert_count": 0}

        class _StubAutomationStore:
            def list_automations(self, user_id: str | None = None, limit: int = 20):
                return []

            def list_runs(self, user_id: str | None = None, limit: int = 24):
                return []

        class _StubAutomationEngine:
            def render_status_page(self, user_id: str | None = None, limit: int = 12):
                return {}

        class _StubWorkflowStore:
            def list_snapshots(self, user_id: str, limit: int = 12):
                return []

        class _StubWorkflowManifestStore:
            def list_manifests(self):
                return []

        class _StubSubagentStatusStore:
            def list_snapshots(self, user_id: str, limit: int = 20):
                return []

        builder = ControlRoomSnapshotBuilder(
            state_store=self.state_store,
            ontology=_StubOntology(),
            memory_manager=_StubMemoryManager(),
            automation_engine=_StubAutomationEngine(),
            automation_store=_StubAutomationStore(),
            delivery_gateway=_StubDeliveryGateway(),
            tool_registry=_StubToolRegistry(),
            subagent_registry=Mock(),
            subagent_status_store=_StubSubagentStatusStore(),
            workflow_store=_StubWorkflowStore(),
            workflow_manifest_store=_StubWorkflowManifestStore(),
            ops_control=Mock(snapshot=lambda event_limit=12, metric_limit=24: {}),
            jobs_root=self.temp_dir / "jobs",
            artifacts_root=self.temp_dir / "sessions" / "artifacts",
        )
        snapshot = builder.build(user_id="ctx-user", agent_name="Somi", model_snapshot={"DEFAULT_MODEL": "test"})
        self.assertIn("context", dict(snapshot.get("tabs") or {}))
        row_ids = {str(row.get("id") or "") for row in list(dict(snapshot.get("tabs") or {}).get("context") or [])}
        self.assertIn("context_budget", row_ids)

    def test_doctor_and_support_bundle_include_context_budget(self) -> None:
        self._seed_sessions()
        doctor = run_somi_doctor(self.temp_dir)
        self.assertIn("context_budget", doctor)

        bundle = write_support_bundle(self.temp_dir, label="phase154")
        self.assertIn("context_budget", bundle)
        markdown_path = Path(str(dict(bundle.get("paths") or {}).get("markdown") or ""))
        self.assertIn("## Context Budget", markdown_path.read_text(encoding="utf-8"))

    def test_context_budget_skips_synthetic_eval_users(self) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        trace = self.state_store.start_turn(
            user_id="stress_user",
            thread_id="thr_synthetic",
            user_text="Synthetic stress turn " + ("noise " * 60),
            routing_prompt="Synthetic benchmark",
            metadata={"surface": "gui"},
            created_at=stamp,
        )
        self.state_store.finish_turn(
            trace=trace,
            assistant_text="Synthetic output " + ("noise " * 60),
            status="completed",
            route="llm_only",
            model_name="test-model",
            routing_prompt="Synthetic benchmark",
            completed_at=stamp,
        )

        report = run_context_budget_status(self.temp_dir, limit=8)
        self.assertEqual(int(report.get("session_count") or 0), 0)
        self.assertEqual(int(report.get("skipped_session_count") or 0), 1)

    def test_context_status_cli_reports_context_budget(self) -> None:
        self._seed_sessions()
        result = subprocess.run(
            [sys.executable, str(ROOT / "somi.py"), "context", "status", "--root", str(self.temp_dir), "--user-id", "ctx-user"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertIn("[Somi Context Budget]", result.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
