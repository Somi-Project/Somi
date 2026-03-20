from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.coding.jobs import CodingJobStore


class CodingStudioPhase6Tests(unittest.TestCase):
    def test_job_store_builds_repair_aware_scorecard(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        store = CodingJobStore(root_dir=Path(root) / "coding_jobs")
        job = store.start_or_resume_job(
            session_id="coding-session-1",
            objective="Repair failing tests and verify the patch",
            workspace_root=str(Path(root) / "workspace"),
            profile_key="python",
            repo_focus_files=["src/app.py", "tests/test_app.py"],
        )
        store.record_step(
            job_id=job["job_id"],
            step_type="verify",
            status="failed",
            command="pytest -q",
            files=["tests/test_app.py"],
            notes="Initial failure reproduced",
        )
        repaired = store.record_step(
            job_id=job["job_id"],
            step_type="repair",
            status="completed",
            command="python -m pytest tests/test_app.py -q",
            files=["src/app.py", "tests/test_app.py"],
            notes="Patch applied and targeted test passed",
        )
        repaired = store.record_step(
            job_id=job["job_id"],
            step_type="verify",
            status="completed",
            command="python -m pytest -q",
            files=["tests/test_app.py"],
            notes="Full verify loop returned green",
        )
        scorecard = dict(repaired.get("scorecard") or {})
        self.assertGreaterEqual(float(scorecard.get("finality_score") or 0.0), 50.0)
        self.assertTrue(bool(scorecard.get("multi_file")))
        self.assertTrue(list(scorecard.get("next_actions") or []))


if __name__ == "__main__":
    unittest.main()
