from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.codingstudio import CodingStudioPanel
from gui.qt import QApplication


class _SnapshotBuilder:
    def build(self, *, user_id: str = "default_user") -> dict:
        del user_id
        return {
            "session": {
                "session_id": "coding_demo",
                "welcome_text": "Hi, welcome to coding mode.",
            },
            "workspace": {
                "profile_display_name": "Python",
                "profile_key": "python",
                "root_path": "C:/tmp/demo",
                "run_command": "python main.py",
                "test_command": "python -m pytest",
            },
            "runtime_rows": [{"key": "python", "label": "Python", "available": True, "version": "3.11"}],
            "health": {"status": "green", "summary": "python ready"},
            "scorecard": {"status": "green", "summary": "tests green"},
            "benchmark_pack": {"label": "Patch loop", "profile_key": "python"},
            "repo_map": {"summary": "focus on app.py", "focus_files": ["app.py"], "hotspot_files": []},
            "active_job": {"status": "active", "job_id": "job_1", "scorecard": {"summary": "score=88", "next_actions": []}},
            "coding_memory": {"summary": "remember app.py and tests"},
            "scratchpad": {"open_loops": ["Run pytest after patching app.py"]},
            "compaction_summary": "[Coding Scratchpad]\n- Objective: keep app.py healthy\n- Focus files: app.py\n- Next action: Run pytest after patching app.py",
            "change_plan": {
                "summary": "targets=app.py | verify=python -m pytest | bounded patch loop",
                "steps": [
                    "Inspect app.py before patching.",
                    "Apply bounded edits to app.py.",
                ],
            },
            "edit_risk": {"risk_level": "medium", "risk_score": 41, "reasons": ["hotspot"]},
            "git_status": {"summary": "main | 1 changed", "changed_files": ["app.py"]},
            "snapshots": [{"snapshot_id": "snap_1"}, {"snapshot_id": "snap_2"}],
            "sandbox": {"summary": "managed workspace"},
            "next_actions": ["Inspect app.py", "Run pytest"],
            "workspace_files": [{"path": "app.py", "kind": "file"}],
            "suggested_commands": ["python -m pytest"],
            "starter_files": ["app.py"],
            "recent_sessions": [{"title": "Demo", "profile": "python", "status": "active", "updated_at": "now"}],
            "skill_hint": {"capability": "git publish"},
        }


class _Controller:
    coding_user_id = "default_user"

    def open_coding_workspace_folder(self):
        return {"ok": True}

    def run_coding_profile_check(self):
        return {"ok": True}

    def run_coding_verify_loop(self):
        return {"ok": True}

    def bootstrap_coding_workspace(self):
        return {"ok": True}

    def draft_coding_skill(self):
        return {"ok": True}

    def send_coding_prompt(self, prompt):
        return prompt

    def open_chat(self):
        return None


class GuiCodingStudioPhase119Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_coding_studio_surfaces_git_and_snapshot_state(self) -> None:
        panel = CodingStudioPanel(_Controller(), snapshot_builder=_SnapshotBuilder())
        self._app.processEvents()
        self.assertIn("main | 1 changed", panel.git_chip.text())
        self.assertEqual(panel.snapshot_chip.text(), "Snapshots: 2")
        self.assertIn("Git: main | 1 changed", panel.welcome_text.toPlainText())
        self.assertIn("Resume summary:", panel.welcome_text.toPlainText())
        self.assertIn("[Coding Scratchpad]", panel.welcome_text.toPlainText())
        self.assertIn("Change plan:", panel.welcome_text.toPlainText())
        self.assertIn("Edit risk: MEDIUM", panel.welcome_text.toPlainText())
        health_rows = [panel.health_list.item(i).text() for i in range(panel.health_list.count())]
        self.assertIn("Snapshots: 2 available", health_rows)
        self.assertIn("Edit risk: MEDIUM (score 41)", health_rows)
        next_actions = [panel.next_actions_list.item(i).text() for i in range(panel.next_actions_list.count())]
        self.assertIn("Open loop: Run pytest after patching app.py", next_actions)


if __name__ == "__main__":
    unittest.main()
