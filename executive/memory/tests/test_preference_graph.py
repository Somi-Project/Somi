from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from executive.memory.manager import Memory3Manager
from executive.memory.preference_graph import build_preference_graph
from executive.memory.store import SQLiteMemoryStore


class PreferenceGraphTests(unittest.TestCase):
    def test_build_preference_graph_groups_rows_and_ranks_profile_first(self) -> None:
        graph = build_preference_graph(
            profile_rows=[
                {"mkey": "name", "value": "Sam", "kind": "profile", "confidence": 0.96, "updated_at": "2026-03-19T00:00:00+00:00"},
                {"mkey": "timezone", "value": "America/Port_of_Spain", "kind": "profile", "confidence": 0.91, "updated_at": "2026-03-19T00:00:01+00:00"},
            ],
            preference_rows=[
                {"mkey": "favorite_drink", "value": "coffee", "kind": "preference", "confidence": 0.88, "updated_at": "2026-03-19T00:00:02+00:00"},
                {"mkey": "favorite_drink", "value": "coffee", "kind": "preference", "confidence": 0.9, "updated_at": "2026-03-19T00:00:03+00:00"},
            ],
        )
        self.assertEqual(graph["node_count"], 3)
        self.assertEqual(graph["profile_count"], 2)
        self.assertEqual(graph["preference_count"], 1)
        self.assertEqual(graph["nodes"][0]["key"], "name")
        self.assertEqual(graph["nodes"][2]["evidence_count"], 2)
        self.assertIn("favorite_drink=coffee", graph["summary"])


class MemoryManagerPreferenceGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_memory_pref_graph_"))
        self.store = SQLiteMemoryStore(db_path=str(self.temp_dir / "memory.sqlite3"))
        self.manager = Memory3Manager(user_id="pref_user", store=self.store)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_manager_builds_preference_graph_and_freezes_it_in_snapshot(self) -> None:
        await self.manager.upsert_fact({"key": "name", "value": "Sam", "kind": "profile", "confidence": 0.96}, user_id="pref_user")
        await self.manager.upsert_fact({"key": "favorite_drink", "value": "coffee", "kind": "preference", "confidence": 0.9}, user_id="pref_user")
        graph = self.manager.build_preference_graph_sync("pref_user")
        self.assertEqual(graph["node_count"], 2)
        self.assertIn("favorite_drink=coffee", graph["summary"])

        await self.manager.build_injected_context("favorite drink", user_id="pref_user")
        frozen = self.manager.frozen_store.read_snapshot("pref_user") or {}
        frozen_graph = dict(frozen.get("preference_graph") or {})
        self.assertEqual(frozen_graph.get("node_count"), 2)
        self.assertIn("name=Sam", str(frozen_graph.get("summary") or ""))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
