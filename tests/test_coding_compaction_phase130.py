from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.coding import CodexControlPlane
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager


class CodingCompactionPhase130Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_coding_compaction_"))
        self.store = CodingSessionStore(root_dir=self.temp_dir / "sessions")
        self.workspace_manager = CodingWorkspaceManager(root_dir=self.temp_dir / "workspaces")
        self.job_store = CodingJobStore(root_dir=self.temp_dir / "jobs")
        self.service = CodingSessionService(
            store=self.store,
            workspace_manager=self.workspace_manager,
            job_store=self.job_store,
        )
        self.control = CodexControlPlane(
            coding_service=self.service,
            store=self.store,
            job_store=self.job_store,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_open_session_persists_scratchpad_and_compaction_summary(self) -> None:
        session = self.control.open_session(user_id="tester", objective="Build a sample python helper", source="unit")
        metadata = dict(session.get("metadata") or {})
        scratchpad = dict(metadata.get("scratchpad") or {})
        summary = str(metadata.get("compaction_summary") or "")
        self.assertIn("Build a sample python helper", str(scratchpad.get("objective") or ""))
        self.assertTrue(list(scratchpad.get("next_actions") or []))
        self.assertIn("[Coding Scratchpad]", summary)
        self.assertIn("Focus files:", summary)

    def test_control_snapshot_exposes_resume_summary_and_updates_after_verify(self) -> None:
        session = self.control.open_session(user_id="tester", objective="Build a sample python helper", source="unit")
        session_id = str(session.get("session_id") or "")
        self.assertTrue(session_id)

        self.control.apply_text_edit(
            session_id=session_id,
            relative_path="README.md",
            content="# Updated Workspace\n\nThis workspace was refreshed by CodexControlPlane.\n",
            notes="refresh readme",
        )
        verify = self.control.run_verify_cycle(session_id=session_id)
        self.assertTrue(verify["ok"])

        snapshot = self.control.build_control_snapshot(session_id=session_id)
        self.assertTrue(snapshot["ok"])
        scratchpad = dict(snapshot.get("scratchpad") or {})
        summary = str(snapshot.get("compaction_summary") or "")
        self.assertTrue(list(scratchpad.get("focus_files") or []))
        self.assertIn("[Coding Scratchpad]", summary)
        self.assertIn("Open loop:", summary)
        self.assertIn("Next action:", summary)


if __name__ == "__main__":
    unittest.main()
