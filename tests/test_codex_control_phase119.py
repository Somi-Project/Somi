from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.coding import CodexControlPlane
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager


def _git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class CodexControlPhase119Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_codex_control_"))
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

    def test_control_snapshot_and_edit_flow(self) -> None:
        session = self.control.open_session(user_id="tester", objective="Build a sample python helper", source="unit")
        session_id = str(session.get("session_id") or "")
        self.assertTrue(session_id)

        snapshot = self.control.build_control_snapshot(session_id=session_id, include_file_previews=True)
        self.assertTrue(snapshot["ok"])
        self.assertFalse(dict(snapshot.get("git") or {}).get("available"))
        self.assertTrue(list(snapshot.get("workspace_files") or []))
        self.assertTrue(dict(snapshot.get("change_plan") or {}).get("steps"))
        self.assertTrue(list(dict(snapshot.get("repo_map") or {}).get("focus_symbols") or []))

        edit = self.control.apply_text_edit(
            session_id=session_id,
            relative_path="README.md",
            content="# Updated Workspace\n\nThis workspace was refreshed by CodexControlPlane.\n",
            notes="refresh readme",
        )
        self.assertTrue(edit["ok"])
        self.assertTrue(list(edit.get("snapshots") or []))
        self.assertTrue(str(dict(edit.get("write") or {}).get("path") or "").endswith("README.md"))
        self.assertIn("risk_level", dict(edit.get("edit_risk") or {}))
        self.assertEqual(list(dict(edit.get("change_plan") or {}).get("targets") or [""])[0], "README.md")

        inspect = self.control.inspect_workspace(session_id=session_id, relative_paths=["README.md"])
        self.assertTrue(inspect["ok"])
        self.assertIn("Updated Workspace", str(dict(inspect["files"][0]).get("content") or ""))

        verify = self.control.run_verify_cycle(session_id=session_id)
        self.assertTrue(verify["ok"])
        self.assertIn("scorecard", verify)
        self.assertTrue(dict(verify.get("active_job") or {}).get("job_id"))

    def test_config_edit_scores_higher_risk_and_plan_change(self) -> None:
        session = self.control.open_session(user_id="tester", objective="Adjust dependencies safely", source="unit")
        session_id = str(session.get("session_id") or "")

        edit = self.control.apply_text_edit(
            session_id=session_id,
            relative_path="pyproject.toml",
            content="[project]\nname = \"demo\"\nversion = \"0.2.0\"\n",
            notes="dependency metadata refresh",
        )
        self.assertTrue(edit["ok"])
        risk = dict(edit.get("edit_risk") or {})
        self.assertIn(str(risk.get("risk_level") or ""), {"high", "critical"})
        self.assertIn("dependency_manifest", list(risk.get("reasons") or []))

        plan = self.control.plan_change(session_id=session_id, relative_paths=["pyproject.toml"])
        self.assertTrue(plan["ok"])
        self.assertIn("pyproject.toml", list(dict(plan.get("change_plan") or {}).get("targets") or []))

    @unittest.skipIf(shutil.which("git") is None, "git is required for publish tests")
    def test_git_commit_push_and_publish_status(self) -> None:
        session = self.control.open_session(user_id="publisher", objective="Prepare a repo for publish", source="unit")
        session_id = str(session.get("session_id") or "")
        root = Path(str(dict(session.get("workspace") or {}).get("root_path") or "")).resolve()

        _git(["init", "-b", "main"], cwd=root)
        _git(["config", "user.email", "somi@example.com"], cwd=root)
        _git(["config", "user.name", "Somi Test"], cwd=root)
        _git(["add", "-A"], cwd=root)
        _git(["commit", "-m", "Initial workspace"], cwd=root)

        remote = self.temp_dir / "remote.git"
        _git(["init", "--bare", str(remote)])
        _git(["remote", "add", "origin", str(remote)], cwd=root)
        _git(["push", "-u", "origin", "main"], cwd=root)

        edit = self.control.apply_text_edit(
            session_id=session_id,
            relative_path="README.md",
            content="# Published Workspace\n\nReady for remote publish.\n",
            notes="prep publish",
        )
        self.assertTrue(edit["ok"])

        status = self.control.git_status(session_id=session_id)
        git_status = dict(status.get("git") or {})
        self.assertTrue(git_status.get("available"))
        self.assertFalse(git_status.get("clean"))
        self.assertIn("README.md", list(git_status.get("changed_files") or []))

        diff = self.control.git_diff(session_id=session_id, relative_path="README.md")
        self.assertTrue(diff["ok"])
        self.assertIn("Published Workspace", str(diff.get("diff") or ""))

        commit = self.control.git_commit(session_id=session_id, message="Update README for publish")
        self.assertTrue(commit["ok"])
        self.assertIn("Update README for publish", str(commit.get("last_commit") or ""))

        publish_status = self.control.publish_status(session_id=session_id, remote="origin", branch="main")
        status_row = dict(publish_status.get("publish_status") or {})
        self.assertTrue(status_row.get("remote_configured"))

        push = self.control.git_push(session_id=session_id, remote="origin", branch="main")
        self.assertTrue(push["ok"])
        self.assertTrue(bool(push.get("publish_requires_confirmation")))
        self.assertTrue(bool(push.get("external_effect")))

        remote_head = _git(["--git-dir", str(remote), "rev-parse", "refs/heads/main"])
        self.assertTrue(remote_head.stdout.strip())
        remote_branch_log = _git(["--git-dir", str(remote), "log", "--oneline", "--max-count", "1", "refs/heads/main"])
        self.assertIn("Update README for publish", remote_branch_log.stdout)

    def test_import_repo_snapshot_builds_repo_context(self) -> None:
        source = self.temp_dir / "source_repo"
        source.mkdir(parents=True, exist_ok=True)
        (source / "app.py").write_text("def answer() -> int:\n    return 42\n", encoding="utf-8")
        (source / "README.md").write_text("# Demo Repo\n", encoding="utf-8")

        imported = self.control.import_repo_snapshot(
            source_root=str(source),
            user_id="snapshot_user",
            objective="Inspect the sample repo",
        )
        self.assertTrue(imported["ok"])
        self.assertEqual(imported["sandbox_backend"], "repo_snapshot")
        self.assertTrue(Path(str(imported.get("workspace_root") or "")).exists())
        files = [str(row.get("path") or "") for row in list(imported.get("workspace_files") or [])]
        self.assertIn("app.py", files)


if __name__ == "__main__":
    unittest.main()
