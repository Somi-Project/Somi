from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.coding.workspace import CodingWorkspaceManager


class CodingToolsPhase3Tests(unittest.TestCase):
    def test_workspace_manager_scaffolds_python_workspace(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        manager = CodingWorkspaceManager(root_dir=Path(root) / "coding_workspaces")
        snapshot = manager.ensure_workspace(
            user_id="phase3-user",
            title="Phase 3 Coding Workspace",
            preferred_slug="phase3",
            language="python",
            profile_key="python",
            metadata={"source": "phase3"},
        )
        workspace_root = Path(snapshot["root_path"])
        self.assertTrue(workspace_root.exists())
        self.assertTrue((workspace_root / "README.md").exists())
        self.assertTrue((workspace_root / ".somi_coding_workspace.json").exists())
        self.assertEqual(snapshot["profile_key"], "python")
        self.assertIn("python", [str(row.get("key") or "") for row in list(snapshot.get("available_runtimes") or [])])


if __name__ == "__main__":
    unittest.main()
