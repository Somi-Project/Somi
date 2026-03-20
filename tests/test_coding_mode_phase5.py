from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager


class _FakeSkillForge:
    def suggest_skill_gap(self, **kwargs) -> dict[str, object]:  # noqa: ANN003
        return {}


class CodingModePhase5Tests(unittest.TestCase):
    def test_open_session_creates_resumable_coding_mode_snapshot(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        service = CodingSessionService(
            store=CodingSessionStore(root_dir=Path(root) / "coding_sessions"),
            workspace_manager=CodingWorkspaceManager(root_dir=Path(root) / "coding_workspaces"),
            job_store=CodingJobStore(root_dir=Path(root) / "coding_jobs"),
            skill_forge=_FakeSkillForge(),
            coding_model="phase5-model",
            agent_profile="coding_worker",
        )
        opened = service.open_session(
            user_id="phase5-user",
            source="gui",
            objective="Debug the Python project and add a regression test",
            metadata={"profile_key": "python"},
        )
        resumed = service.open_session(
            user_id="phase5-user",
            source="gui",
            objective="Debug the Python project and add a regression test",
            metadata={"profile_key": "python"},
            resume_active=True,
        )
        self.assertEqual(opened["status"], "active")
        self.assertEqual(resumed["session_id"], opened["session_id"])
        self.assertIn("Hi, welcome to coding mode.", opened["welcome_text"])
        self.assertTrue(dict(resumed.get("metadata") or {}).get("active_job"))


if __name__ == "__main__":
    unittest.main()
