from __future__ import annotations

import tempfile
import unittest

from gui.researchstudio_data import ResearchStudioSnapshotBuilder
from workshop.toolbox.research_supermode.store import ResearchSupermodeStore


class ResearchStudioSnapshotTests(unittest.TestCase):
    def test_snapshot_includes_active_progress_memory_and_subagent_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ResearchSupermodeStore(root_dir=tmpdir)
            store.write_job(
                {
                    "job_id": "rjob_demo",
                    "user_id": "default_user",
                    "query": "latest hypertension guidelines",
                    "status": "active",
                    "progress": {"summary": "sources=4 trusted=3 claims=5 conflicts=0 coverage=76.0"},
                    "memory": {"summary": "Recent passes: latest hypertension guidelines | Observed domains: acc.org, heart.org"},
                    "subagents": [
                        {"id": "discovery_scout", "status": "completed", "summary": "Ranked 4 sources."},
                        {"id": "coverage_analyst", "status": "completed", "summary": "coverage looks good."},
                    ],
                }
            )
            builder = ResearchStudioSnapshotBuilder(store=store)
            snapshot = builder.build(user_id="default_user")
            summary = dict(snapshot.get("summary") or {})
            self.assertEqual(summary.get("active_job_id"), "rjob_demo")
            self.assertIn("sources=4", str(summary.get("active_progress_summary") or ""))
            self.assertIn("Recent passes", str(summary.get("active_memory_summary") or ""))
            self.assertIn("discovery_scout", str(summary.get("active_subagent_summary") or ""))


if __name__ == "__main__":
    unittest.main()
