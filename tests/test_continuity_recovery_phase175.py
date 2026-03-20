from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from ops.continuity_recovery import build_continuity_recovery_snapshot


ROOT = Path(__file__).resolve().parents[1]


class ContinuityRecoveryPhase175Tests(unittest.TestCase):
    def test_snapshot_surfaces_domains_and_workflows(self) -> None:
        report = build_continuity_recovery_snapshot(ROOT, runtime_mode="survival", query="restore shelter power and battery charging")
        self.assertTrue(bool(report.get("ok")))
        self.assertGreaterEqual(int(report.get("workflow_count") or 0), 4)
        self.assertIn("power", list(report.get("domains") or []))
        recommended = list(report.get("recommended_workflows") or [])
        self.assertTrue(recommended)
        self.assertEqual(str(recommended[0].get("manifest_id") or ""), "continuity_power_recovery")

    def test_cli_continuity_returns_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "somi.py"),
                "offline",
                "continuity",
                "--json",
                "--root",
                str(ROOT),
                "--runtime-mode",
                "survival",
                "--query",
                "sterilization and sanitation plan",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"offline continuity CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertTrue(bool(payload.get("continuity_ready")))
        names = [str(item.get("manifest_id") or "") for item in list(payload.get("recommended_workflows") or [])]
        self.assertIn("continuity_sanitation", names)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
