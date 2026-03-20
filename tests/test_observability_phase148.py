from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.control_plane import OpsControlPlane
from ops.observability import build_observability_digest, run_observability_snapshot
from ops.support_bundle import write_support_bundle


ROOT = Path(__file__).resolve().parents[1]


class ObservabilityPhase148Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_observability_phase148_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture" / "TRUST_BOUNDARIES.md").write_text("# Trust\n", encoding="utf-8")
        checkpoint = self.temp_dir / "audit" / "backups" / "phase148_demo_checkpoint"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "update.md").write_text("# Update\n", encoding="utf-8")
        (checkpoint / "phase_upgrade.md").write_text("# Phase\n", encoding="utf-8")
        self.ops = OpsControlPlane(root_dir=self.temp_dir / "sessions" / "ops")
        self._seed_runtime_signals()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_runtime_signals(self) -> None:
        self.ops.record_tool_metric(
            tool_name="browser_fetch",
            success=False,
            elapsed_ms=5200,
            backend="local",
            channel="chat",
            risk_tier="LOW",
            approved=True,
        )
        self.ops.record_tool_metric(
            tool_name="browser_fetch",
            success=True,
            elapsed_ms=4800,
            backend="local",
            channel="chat",
            risk_tier="LOW",
            approved=True,
        )
        self.ops.record_tool_metric(
            tool_name="local_pack_search",
            success=True,
            elapsed_ms=180,
            backend="local",
            channel="chat",
            risk_tier="LOW",
            approved=True,
        )
        self.ops.record_model_metric(
            model_name="somi-main",
            route="research",
            latency_ms=6100,
            prompt_chars=1600,
            output_chars=700,
        )
        task = self.ops.create_background_task(
            user_id="tester",
            objective="Continue unattended research while the user is away",
            task_type="research",
            surface="gui",
        )
        self.ops.fail_background_task(
            str(task.get("task_id") or ""),
            error="Search worker stalled after the last retry.",
            recoverable=True,
            recommended_action="Resume on the foreground surface.",
        )
        self.ops.record_policy_decision(
            surface="telegram",
            decision="blocked",
            reason="Remote action needs approval before execution.",
        )

    def test_build_observability_digest_flags_hotspots_and_recovery(self) -> None:
        snapshot = self.ops.snapshot(event_limit=12, metric_limit=12)
        digest = build_observability_digest(snapshot)

        self.assertIn(str(digest.get("status") or ""), {"warn", "critical"})
        self.assertGreaterEqual(int(digest.get("alert_count") or 0), 1)
        self.assertEqual(str(list(digest.get("tool_hotspots") or [])[0].get("tool_name") or ""), "browser_fetch")
        self.assertGreaterEqual(int(digest.get("recovery_pressure") or 0), 1)
        self.assertTrue(list(digest.get("recommendations") or []))

    def test_run_observability_snapshot_reads_ops_store(self) -> None:
        report = run_observability_snapshot(self.temp_dir)
        digest = dict(report.get("observability") or {})
        self.assertTrue(bool(report.get("ok")))
        self.assertIn(str(digest.get("status") or ""), {"warn", "critical"})
        self.assertIn("browser_fetch", json.dumps(digest, ensure_ascii=False))

    def test_digest_ignores_synthetic_eval_noise(self) -> None:
        snapshot = {
            "recent_metrics": [
                {"metric_type": "tool", "tool_name": "breaker.eval.tool", "success": False, "elapsed_ms": 0, "meta": {"failure_streak": 2}},
                {"metric_type": "tool", "tool_name": "browser_fetch", "success": False, "elapsed_ms": 4100, "channel": "chat"},
            ],
            "recent_events": [
                {
                    "type": "policy_decision",
                    "decision": "blocked",
                    "surface": "tool_runtime",
                    "reason": "ToolRuntimeError: Tool research.artifacts is not exposed to channel 'heartbeat'",
                    "payload": {"tool": "research.artifacts"},
                },
                {
                    "type": "policy_decision",
                    "decision": "blocked",
                    "surface": "tool_runtime",
                    "reason": "policy blocked a real tool",
                    "payload": {"tool": "browser_fetch"},
                },
            ],
            "background_tasks": {"counts": {}, "retry_ready_count": 0, "failed_count": 0},
        }
        digest = build_observability_digest(snapshot)
        self.assertEqual(str(list(digest.get("tool_hotspots") or [])[0].get("tool_name") or ""), "browser_fetch")
        self.assertEqual(int(digest.get("blocked_policy_count") or 0), 1)

    def test_support_bundle_includes_observability(self) -> None:
        bundle = write_support_bundle(self.temp_dir, label="phase148")
        observability = dict(bundle.get("observability") or {})
        self.assertGreaterEqual(int(observability.get("alert_count") or 0), 1)
        markdown_path = Path(str(dict(bundle.get("paths") or {}).get("markdown") or ""))
        self.assertTrue(markdown_path.exists())
        self.assertIn("## Observability", markdown_path.read_text(encoding="utf-8"))

    def test_control_room_observability_rows_include_hotspots(self) -> None:
        builder = ControlRoomSnapshotBuilder(
            state_store=Mock(),
            ontology=Mock(),
            memory_manager=Mock(),
            automation_engine=Mock(),
            automation_store=Mock(),
            delivery_gateway=Mock(),
            tool_registry=Mock(),
            subagent_registry=Mock(),
            subagent_status_store=Mock(),
            workflow_store=Mock(),
            workflow_manifest_store=Mock(),
            ops_control=self.ops,
        )
        rows = builder._observability_rows(
            ops_snapshot=self.ops.snapshot(event_limit=12, metric_limit=12),
            release_report=None,
            freeze_report=None,
            offline_report=None,
        )
        row_ids = {str(row.get("id") or "") for row in rows}
        self.assertIn("latency_hotspots", row_ids)
        self.assertIn("recovery_watchlist", row_ids)

    def test_observability_cli_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "somi.py"), "observability", "snapshot", "--json", "--root", str(self.temp_dir)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"observability CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(int(dict(payload.get("observability") or {}).get("alert_count") or 0), 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
