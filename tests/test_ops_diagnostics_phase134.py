from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ops.backup_verifier import verify_recent_backups
from ops.doctor import run_somi_doctor
from ops.support_bundle import write_support_bundle


ROOT = Path(__file__).resolve().parents[1]


class OpsDiagnosticsPhase134Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_ops_phase134_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / ".venv").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture" / "TRUST_BOUNDARIES.md").write_text("# Trust\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_phase_checkpoint(self, name: str = "phase_demo_20260319") -> Path:
        checkpoint = self.temp_dir / "audit" / "backups" / name
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "docs" / "release").mkdir(parents=True, exist_ok=True)
        (checkpoint / "docs" / "release" / "FRAMEWORK_RELEASE_NOTES.md").write_text("# Update\n", encoding="utf-8")
        (checkpoint / "docs" / "release" / "UPGRADE_PATH_VERIFIED.md").write_text("# Phase\n", encoding="utf-8")
        return checkpoint

    def test_verify_recent_backups_accepts_phase_checkpoints_from_audit_root(self) -> None:
        self._create_phase_checkpoint()
        report = verify_recent_backups(self.temp_dir / "backups", limit=3)

        self.assertEqual(int(report.get("verified_count") or 0), 1)
        self.assertIn(str(self.temp_dir / "audit" / "backups"), list(report.get("roots") or []))
        self.assertEqual(str(list(report.get("reports") or [])[0].get("mode") or ""), "phase_checkpoint")

    def test_verify_recent_backups_accepts_patchwave_checkpoint_without_upgrade_log(self) -> None:
        checkpoint = self.temp_dir / "audit" / "backups" / "phase134_patchwave_runtime_fix"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "backup_verifier.py").write_text("print('backup')\n", encoding="utf-8")
        (checkpoint / "somi.py").write_text("print('somi')\n", encoding="utf-8")

        report = verify_recent_backups(self.temp_dir / "backups", limit=3)
        self.assertEqual(int(report.get("verified_count") or 0), 1)
        self.assertEqual(str(list(report.get("reports") or [])[0].get("mode") or ""), "phase_checkpoint")

    def test_doctor_uses_audit_backup_root_and_counts_available_tools(self) -> None:
        self._create_phase_checkpoint()
        report = run_somi_doctor(self.temp_dir)

        self.assertTrue(bool(report.get("ok")))
        self.assertIn(str(self.temp_dir / "audit" / "backups"), list(report.get("backup_roots") or []))
        self.assertIn("available_count", dict(report.get("tools") or {}))
        self.assertEqual(int(dict(report.get("tools") or {}).get("total") or 0), int(dict(report.get("tools") or {}).get("available_count") or 0))

    def test_support_bundle_writes_json_and_markdown(self) -> None:
        self._create_phase_checkpoint()
        bundle = write_support_bundle(self.temp_dir, label="phase134")

        paths = dict(bundle.get("paths") or {})
        json_path = Path(str(paths.get("json") or ""))
        md_path = Path(str(paths.get("markdown") or ""))
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        self.assertNotEqual(str(bundle.get("status") or ""), "blocked")
        self.assertIn("Somi Support Bundle", md_path.read_text(encoding="utf-8"))

    def test_support_bundle_cli_runs_without_blocking_on_audit_backups(self) -> None:
        self._create_phase_checkpoint()
        result = subprocess.run(
            [sys.executable, str(ROOT / "somi.py"), "support", "bundle", "--root", str(self.temp_dir), "--no-write"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"support bundle CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("[Somi Support Bundle]", result.stdout)

    def test_verify_backup_dir_uses_current_cli_path_in_critical_sample(self) -> None:
        checkpoint = self._create_phase_checkpoint("phase155_demo_20260319")
        (checkpoint / "somi.py").write_text("print('somi')\n", encoding="utf-8")
        report = verify_recent_backups(self.temp_dir / "backups", limit=3)
        first = dict(list(report.get("reports") or [])[0])
        self.assertIn("somi.py", list(first.get("present") or []))
        self.assertNotIn("somicontroller.py", list(first.get("missing") or []))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
