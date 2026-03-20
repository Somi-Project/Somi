from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from executive.memory.manager import Memory3Manager
from executive.memory.retrieval import infer_memory_focus
from executive.memory.store import SQLiteMemoryStore


class MemoryAdaptivePhase157Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_memory_phase157_"))
        self.store = SQLiteMemoryStore(db_path=str(self.temp_dir / "memory.sqlite3"))
        self.manager = Memory3Manager(user_id="adaptive_user", store=self.store)
        await self.manager.upsert_fact(
            {"key": "timezone", "value": "America/Port_of_Spain", "kind": "profile", "confidence": 0.94},
            user_id="adaptive_user",
        )
        await self.manager.write_typed_memory(
            "project",
            "repair_plan",
            "Refactor the inverter monitor and keep verify loops short.",
            user_id="adaptive_user",
            confidence=0.93,
        )
        await self.manager.write_typed_memory(
            "object",
            "pump_manual",
            "Manual excerpt about pump pressure and flow diagnostics.",
            user_id="adaptive_user",
            confidence=0.89,
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_infer_memory_focus_detects_personal_and_coding_queries(self) -> None:
        self.assertEqual(infer_memory_focus("What is my timezone?"), "personal")
        self.assertEqual(infer_memory_focus("Find the bug in this Python file and rerun tests"), "coding")

    async def test_write_typed_memory_assigns_adaptive_lanes(self) -> None:
        project_rows = self.store.latest_by_scope("adaptive_user", "project_memory", limit=3)
        object_rows = self.store.latest_by_scope("adaptive_user", "object_memory", limit=3)
        self.assertEqual(str(project_rows[0].get("lane") or ""), "workflows")
        self.assertEqual(str(object_rows[0].get("lane") or ""), "evidence")

    async def test_build_injected_context_records_focus_in_snapshot(self) -> None:
        await self.manager.build_injected_context(
            "Which file should I edit in the repo and what is the repair plan?",
            user_id="adaptive_user",
        )
        snapshot = self.manager.frozen_store.read_snapshot("adaptive_user") or {}
        trace = dict(snapshot.get("retrieval_trace") or {})
        self.assertEqual(str(snapshot.get("focus") or ""), "coding")
        self.assertEqual(str(trace.get("focus") or ""), "coding")

    async def test_memory_review_reports_lane_counts_and_actions(self) -> None:
        review = self.manager.build_memory_review_sync("adaptive_user", limit=6, review_window=96)
        lane_counts = dict(review.get("lane_counts") or {})
        actions = list(review.get("suggested_actions") or [])
        self.assertGreaterEqual(int(lane_counts.get("pinned") or 0), 1)
        self.assertGreaterEqual(int(lane_counts.get("workflows") or 0), 1)
        self.assertIn("promote_repeated_memory", actions)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
