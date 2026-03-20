from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ops.backup_creator import create_phase_backup, format_backup_creation


ROOT = Path(__file__).resolve().parents[1]


class BackupCreatorPhase140Tests(unittest.TestCase):
    def test_create_phase_backup_skips_nested_backup_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ops").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "release").mkdir(parents=True, exist_ok=True)
            (root / "ops" / "tool.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "README.md").write_text("# tmp\n", encoding="utf-8")
            (root / "docs" / "release" / "FRAMEWORK_RELEASE_NOTES.md").write_text("# roadmap\n", encoding="utf-8")
            (root / "audit" / "backups" / "old").mkdir(parents=True, exist_ok=True)
            (root / "audit" / "backups" / "old" / "nested.txt").write_text("skip\n", encoding="utf-8")
            (root / "audit" / "external_repos" / "repo").mkdir(parents=True, exist_ok=True)
            (root / "audit" / "external_repos" / "repo" / "README.md").write_text("skip\n", encoding="utf-8")
            (root / ".venv" / "Lib").mkdir(parents=True, exist_ok=True)
            (root / ".venv" / "Lib" / "site.py").write_text("skip\n", encoding="utf-8")
            (root / "phase999_tmp").mkdir(parents=True, exist_ok=True)
            (root / "phase999_tmp" / "junk.txt").write_text("skip\n", encoding="utf-8")

            report = create_phase_backup(root, label="phase140_smoke")

            self.assertTrue(report["ok"], report)
            backup_dir = Path(report["backup_dir"])
            self.assertTrue((backup_dir / "ops" / "tool.py").exists())
            self.assertTrue((backup_dir / "README.md").exists())
            self.assertFalse((backup_dir / "audit" / "backups").exists())
            self.assertFalse((backup_dir / "audit" / "external_repos").exists())
            self.assertFalse((backup_dir / ".venv").exists())
            self.assertFalse((backup_dir / "phase999_tmp").exists())

    def test_create_phase_backup_supports_targeted_include_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "architecture" / "SYSTEM_MAP.md").write_text("# map\n", encoding="utf-8")
            (root / "ops").mkdir(parents=True, exist_ok=True)
            (root / "ops" / "helper.py").write_text("print('helper')\n", encoding="utf-8")
            (root / "README.md").write_text("# root\n", encoding="utf-8")

            report = create_phase_backup(
                root,
                label="phase140_targeted",
                include_paths=["docs/architecture", "README.md"],
            )

            self.assertTrue(report["ok"], report)
            backup_dir = Path(report["backup_dir"])
            self.assertTrue((backup_dir / "docs" / "architecture" / "SYSTEM_MAP.md").exists())
            self.assertTrue((backup_dir / "README.md").exists())
            self.assertFalse((backup_dir / "ops").exists())

    def test_backup_cli_create_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ops").mkdir(parents=True, exist_ok=True)
            (root / "ops" / "tool.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "README.md").write_text("# tmp\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "somi.py"),
                    "backup",
                    "create",
                    "--json",
                    "--root",
                    str(root),
                    "--label",
                    "phase140_cli",
                    "--include",
                    "README.md,ops",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                self.fail(f"backup create CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("ok"))
            self.assertTrue(Path(payload["backup_dir"]).exists())
            self.assertTrue((Path(payload["backup_dir"]) / "ops" / "tool.py").exists())

    def test_format_backup_creation_surfaces_key_counts(self) -> None:
        text = format_backup_creation(
            {
                "ok": True,
                "backup_dir": "C:/tmp/backup",
                "stats": {
                    "copied_roots": 2,
                    "copied_files": 10,
                    "skipped_dirs": 1,
                    "skipped_files": 3,
                },
                "missing": [],
            }
        )
        self.assertIn("copied_files: 10", text)
        self.assertIn("backup_dir: C:/tmp/backup", text)


if __name__ == "__main__":
    unittest.main()
