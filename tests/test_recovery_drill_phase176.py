from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from audit.recovery_drill import run_recovery_drill


ROOT = Path(__file__).resolve().parents[1]


class RecoveryDrillPhase176Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_recovery_drill_phase176_"))
        shutil.copytree(ROOT / "knowledge_packs", self.temp_dir / "knowledge_packs")
        shutil.copytree(ROOT / "workflow_runtime" / "manifests", self.temp_dir / "workflow_runtime" / "manifests")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recovery_drill_passes_on_seeded_assets(self) -> None:
        report = run_recovery_drill(self.temp_dir, runtime_mode="survival", scenario="blackout")
        self.assertTrue(bool(report.get("ok")))
        checks = {str(item.get("name") or ""): bool(item.get("ok")) for item in list(report.get("checks") or [])}
        self.assertTrue(checks.get("survival_mode_profile"))
        self.assertTrue(checks.get("workflow_resume_snapshot"))
        self.assertTrue(checks.get("node_exchange_round_trip"))

    def test_cli_recovery_drill_returns_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "somi.py"),
                "offline",
                "drill",
                "--json",
                "--root",
                str(self.temp_dir),
                "--runtime-mode",
                "survival",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"offline drill CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(str(payload.get("scenario") or ""), "blackout")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
