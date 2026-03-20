from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from automations.engine import AutomationEngine
from automations.store import AutomationStore
from gateway.manager import DeliveryGateway
from search.session_search import SessionSearchService
from state import SessionEventStore


class DeliveryAutomationsPhase9Tests(unittest.TestCase):
    def test_due_automation_delivers_session_digest(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        state_store = SessionEventStore(db_path=Path(root) / "state.sqlite3")
        trace = state_store.start_turn(
            user_id="phase9-user",
            thread_id="release",
            user_text="What was the launch checklist decision?",
            routing_prompt="launch checklist",
        )
        state_store.finish_turn(
            trace=trace,
            assistant_text="The launch checklist decision was to verify backups, smoke the GUI, and rerun the search benchmark.",
            status="completed",
            route="llm_only",
            model_name="phase9-test",
            routing_prompt="launch checklist",
            latency_ms=37,
        )
        gateway = DeliveryGateway(root_dir=Path(root) / "delivery")
        store = AutomationStore(db_path=Path(root) / "automations.sqlite3")
        searcher = SessionSearchService(
            state_store=state_store,
            artifacts_root=Path(root) / "artifacts",
            jobs_root=Path(root) / "jobs",
        )
        engine = AutomationEngine(store=store, gateway=gateway, session_search=searcher, timezone_name="UTC")
        now = datetime(2026, 3, 18, 9, 0, tzinfo=timezone.utc)
        automation = engine.create_automation(
            name="Release digest",
            user_id="phase9-user",
            schedule_text="every day at 9 am",
            channel="desktop",
            automation_type="session_digest",
            payload={"query": "launch checklist", "thread_id": "release", "limit": 3, "days": 30},
            now=now,
        )
        store.update_schedule(str(automation.get("automation_id") or ""), next_run_at=now.isoformat(), last_run_at="")
        results = engine.run_due(now=now, limit=5)
        status_page = engine.render_status_page(user_id="phase9-user", limit=5)
        outbox = gateway.list_messages("desktop", box="outbox", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["receipt"]["status"], "delivered")
        self.assertTrue(outbox)
        self.assertIn("launch checklist", str(outbox[-1].get("body") or "").lower())
        self.assertIn("Release digest", status_page)


if __name__ == "__main__":
    unittest.main()
