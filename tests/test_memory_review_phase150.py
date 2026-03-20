from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from executive.memory.manager import Memory3Manager
from executive.memory.store import SQLiteMemoryStore
from gui.controlroom_data import ControlRoomSnapshotBuilder


class MemoryReviewPhase150Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_memory_review_phase150_"))
        self.store = SQLiteMemoryStore(db_path=str(self.temp_dir / "memory.sqlite3"))
        self.manager = Memory3Manager(user_id="review_user", store=self.store)

        await self.manager.upsert_fact(
            {"key": "timezone", "value": "America/New_York", "kind": "profile", "confidence": 0.94},
            user_id="review_user",
        )
        await self.manager.upsert_fact(
            {"key": "timezone", "value": "America/Port_of_Spain", "kind": "profile", "confidence": 0.97},
            user_id="review_user",
        )
        await self.manager.write_typed_memory(
            "project",
            "repair_plan",
            "Inspect the inverter weekly and keep spare fuses nearby.",
            user_id="review_user",
            confidence=0.95,
        )
        self.store.write_item(
            {
                "id": "stale_profile_item",
                "user_id": "review_user",
                "lane": "pinned",
                "type": "fact",
                "entity": "user",
                "mkey": "default_location",
                "value": "Shelter B",
                "kind": "profile",
                "bucket": "identity",
                "importance": 0.95,
                "replaced_by": None,
                "text": "default_location: Shelter B",
                "tags": "profile pinned",
                "confidence": 0.91,
                "status": "active",
                "expires_at": None,
                "scope": "profile",
                "mem_type": "fact",
                "entities_json": None,
                "tags_json": None,
                "supersedes_id": None,
                "contradicts_id": None,
                "created_at": "2025-11-01T00:00:00+00:00",
                "updated_at": "2025-11-01T00:00:00+00:00",
                "last_used_at": None,
                "slot_key": "profile.default_location",
            }
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_memory_review_detects_promotion_conflicts_and_stale_rows(self) -> None:
        review = self.manager.build_memory_review_sync("review_user", limit=6, review_window=96)

        self.assertGreaterEqual(int(review.get("promotion_count") or 0), 1)
        self.assertTrue(
            any(str(item.get("key") or "") == "repair_plan" for item in list(review.get("promotion_candidates") or []))
        )
        self.assertTrue(any(str(item.get("key") or "") == "timezone" for item in list(review.get("conflict_watch") or [])))
        self.assertTrue(
            any(str(item.get("key") or "") == "default_location" for item in list(review.get("stale_watch") or []))
        )
        self.assertIn(str(review.get("status") or ""), {"watch", "warn"})

    async def test_frozen_snapshot_captures_memory_review(self) -> None:
        await self.manager.build_injected_context("What is my repair plan?", user_id="review_user")
        frozen = self.manager.frozen_store.read_snapshot("review_user") or {}
        review = dict(frozen.get("memory_review") or {})

        self.assertGreaterEqual(int(review.get("promotion_count") or 0), 1)
        self.assertIn("summary", review)
        self.assertIn("conflict_count", review)

    async def test_control_room_memory_rows_include_review_queue(self) -> None:
        builder = ControlRoomSnapshotBuilder(
            state_store=Mock(),
            ontology=Mock(),
            memory_manager=self.manager,
            automation_engine=Mock(),
            automation_store=Mock(),
            delivery_gateway=Mock(),
            tool_registry=Mock(),
            subagent_registry=Mock(),
            subagent_status_store=Mock(),
            workflow_store=Mock(),
            workflow_manifest_store=Mock(),
            ops_control=Mock(),
        )

        rows = builder._memory_rows(user_id="review_user")
        row_map = {str(row.get("id") or ""): row for row in rows}

        self.assertIn("memory_review", row_map)
        self.assertIn("promote=", str(row_map["memory_review"].get("subtitle") or ""))
        self.assertIn("lanes=", str(row_map["memory_review"].get("subtitle") or ""))
        self.assertEqual(str(row_map["memory_hygiene"].get("status") or ""), "warn")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
