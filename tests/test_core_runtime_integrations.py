from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from gateway.service import GatewayService
from heartbeat.events import make_event
from heartbeat.integrations.gui_bridge import HeartbeatGUIBridge
from heartbeat.service import HeartbeatService
from workflow_runtime.manifests import WorkflowManifestStore, normalize_manifest
from workflow_runtime.runner import RestrictedWorkflowRunner, WorkflowRunStore
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager


ROOT = Path(__file__).resolve().parents[1]


class _FakeHeartbeatTask:
    name = "test_task"
    min_interval_seconds = 0
    enabled_flag_name = None

    def should_run(self, ctx) -> bool:  # noqa: ANN001
        return True

    def run(self, ctx) -> list[dict[str, object]]:  # noqa: ANN001
        return [
            make_event(
                "WARN",
                "test",
                "Synthetic heartbeat signal",
                detail="Exercise UI bridge and event accounting",
                timezone=ctx.settings.get("SYSTEM_TIMEZONE", "UTC"),
            )
        ]


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def run(self, tool_name: str, args: dict[str, object], ctx: dict[str, object]) -> dict[str, object]:
        self.calls.append((tool_name, dict(args), dict(ctx)))
        return {"ok": True, "formatted": f"echo:{args.get('value', '')}"}


class _FakeSkillForge:
    def suggest_skill_gap(self, **kwargs) -> dict[str, object]:  # noqa: ANN003
        return {}


class CoreRuntimeIntegrationTests(unittest.TestCase):
    def test_eval_harness_runs_from_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "eval_harness.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"eval_harness CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads((ROOT / "sessions" / "evals" / "latest_eval_harness.json").read_text(encoding="utf-8"))
        self.assertTrue(payload.get("ok"))
        self.assertGreaterEqual(int(payload.get("passed") or 0), 10)

    def test_heartbeat_service_and_gui_bridge_surface_warn_state(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        settings = types.SimpleNamespace(
            SYSTEM_TIMEZONE="UTC",
            HEARTBEAT_ENABLED=True,
            HEARTBEAT_MODE="MONITOR",
            HEARTBEAT_TICK_SECONDS=1,
            HB_MAX_UI_EVENTS_PER_DRAIN=10,
            HB_MAX_EVENTS_BUFFER=32,
            HB_ALIVE_BREADCRUMB_MINUTES=1,
            HB_EVENT_DEDUPE_COOLDOWN_SECONDS=1,
            HB_LOG_PATH=str(Path(tmp) / "heartbeat.log"),
        )
        service = HeartbeatService(settings_module=settings)
        self.addCleanup(self._close_logger_handlers, service._logger)
        service._registry._tasks = [_FakeHeartbeatTask()]

        service._emit_lifecycle("Heartbeat test boot")
        service._run_tasks(service._now())
        drained = service.drain_events(10)
        bridge = HeartbeatGUIBridge(service)
        state = service.get_status()["state"]

        self.assertGreaterEqual(len(drained), 2)
        self.assertEqual(int(state.get("warn_count") or 0), 1)
        self.assertIn("WARN", bridge.get_label_text())
        self.assertIn("Mode:", bridge.get_status_tooltip())

    def test_gateway_service_tracks_sessions_nodes_and_health(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        service = GatewayService(root_dir=tmp)
        session = service.register_session(
            user_id="user-1",
            surface="telegram",
            client_id="tg-main",
            client_label="Main Telegram",
            auth_mode="local",
            scopes=["deliver.mobile"],
        )
        self.assertEqual(session["surface"], "telegram")

        health = service.record_health(
            service_id="telegram-bot",
            surface="telegram",
            status="healthy",
            summary="Polling normally",
        )
        self.assertEqual(health["status"], "healthy")

        node = service.register_node(
            user_id="user-1",
            node_type="browser",
            node_id="browser-node-1",
            client_label="Desktop Browser",
            capabilities=["browser.read", "browser.action"],
        )
        self.assertEqual(node["node_type"], "browser_node")

        beat = service.heartbeat_node(
            "browser-node-1",
            status="online",
            capabilities=["browser.read", "browser.action", "browser.snapshot"],
        )
        self.assertIn("browser.snapshot", beat["capabilities"])

        snapshot = service.snapshot(limit=12)
        self.assertTrue(snapshot["sessions"])
        self.assertTrue(snapshot["health"])
        self.assertTrue(snapshot["nodes"])

    def test_workflow_runner_executes_and_enforces_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _FakeRuntime()
            manifest_store = WorkflowManifestStore(root_dir=Path(tmp) / "manifests")
            run_store = WorkflowRunStore(root_dir=Path(tmp) / "runs")
            runner = RestrictedWorkflowRunner(runtime=runtime, run_store=run_store)

            manifest = manifest_store.save(
                {
                    "manifest_id": "echo_flow",
                    "name": "Echo Flow",
                    "script": 'result = tool("demo.echo", {"value": inputs["value"]})',
                    "allowed_tools": ["demo.echo"],
                    "timeout_seconds": 20,
                    "max_tool_calls": 2,
                }
            )
            completed = runner.run_manifest(manifest, user_id="user-1", thread_id="thread-a", inputs={"value": "ping"})
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(runtime.calls[0][0], "demo.echo")
            self.assertEqual(completed["tool_events"][0]["tool"], "demo.echo")

            blocked = runner.run_manifest(
                normalize_manifest(
                    {
                        "manifest_id": "blocked_flow",
                        "name": "Blocked Flow",
                        "script": 'result = tool("demo.blocked", {"value": 1})',
                        "allowed_tools": ["demo.echo"],
                    }
                ),
                user_id="user-1",
                thread_id="thread-a",
            )
            self.assertEqual(blocked["status"], "failed")
            self.assertIn("allowlisted", str(blocked.get("error") or ""))

    def test_coding_session_service_opens_and_resumes_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = CodingSessionService(
                store=CodingSessionStore(root_dir=root / "coding_sessions"),
                workspace_manager=CodingWorkspaceManager(root_dir=root / "coding_workspaces"),
                job_store=CodingJobStore(root_dir=root / "coding_jobs"),
                skill_forge=_FakeSkillForge(),
                coding_model="test-model",
                agent_profile="coding_worker",
            )
            opened = service.open_session(
                user_id="user-1",
                source="gui",
                objective="Fix the Python module bug and add a regression test",
                metadata={"profile_key": "python"},
            )
            workspace_root = Path(opened["workspace"]["root_path"])
            self.assertEqual(opened["status"], "active")
            self.assertTrue(workspace_root.exists())
            self.assertTrue((workspace_root / ".somi_coding_workspace.json").exists())
            self.assertIn("Hi, welcome to coding mode.", opened["welcome_text"])

            resumed = service.open_session(
                user_id="user-1",
                source="gui",
                objective="Fix the Python module bug and add a regression test",
                metadata={"profile_key": "python"},
                resume_active=True,
            )
            self.assertEqual(resumed["session_id"], opened["session_id"])
            self.assertTrue(dict(resumed.get("metadata") or {}).get("active_job"))

    @staticmethod
    def _close_logger_handlers(logger) -> None:  # noqa: ANN001
        for handler in list(getattr(logger, "handlers", [])):
            try:
                handler.close()
            finally:
                logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
