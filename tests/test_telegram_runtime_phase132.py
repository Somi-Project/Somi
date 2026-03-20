from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import shutil

from gateway.service import GatewayService
from state import SessionEventStore
from workshop.integrations.telegram_runtime import (
    TelegramRuntimeBridge,
    build_telegram_reply_bundle,
)
from agent_methods import response_methods


class TelegramRuntimeBridgeTests(unittest.TestCase):
    def test_followup_reuses_active_thread(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        bridge = TelegramRuntimeBridge(
            gateway_service=GatewayService(root_dir=Path(tmp) / "gateway"),
            state_store=SessionEventStore(db_path=Path(tmp) / "state.sqlite3"),
        )
        thread_id = bridge.resolve_thread_id(
            user_id="user-1",
            prompt="also add tests for that",
            conversation_id="12345",
            active_thread_id="thr_existing",
            active_conversation_id="12345",
            active_updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertEqual(thread_id, "thr_existing")

    def test_resume_prompt_picks_latest_cross_surface_thread(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = SessionEventStore(db_path=Path(tmp) / "state.sqlite3")
        bridge = TelegramRuntimeBridge(
            gateway_service=GatewayService(root_dir=Path(tmp) / "gateway"),
            state_store=store,
        )
        trace = store.start_turn(
            user_id="shared-user",
            thread_id="thr_gui_plan",
            user_text="Build the release plan",
            routing_prompt="Build the release plan",
            metadata={"surface": "gui", "conversation_id": "desktop-main"},
        )
        store.finish_turn(
            trace=trace,
            assistant_text="Here is the release plan.",
            status="completed",
            route="continuity_artifact",
            model_name="test-model",
            routing_prompt="Build the release plan",
            latency_ms=10,
        )
        thread_id = bridge.resolve_thread_id(
            user_id="shared-user",
            prompt="continue with that plan",
            conversation_id="tg:dm",
        )
        self.assertEqual(thread_id, "thr_gui_plan")

    def test_owner_sessions_are_paired_remote_and_guest_sessions_are_untrusted(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        bridge = TelegramRuntimeBridge(
            gateway_service=GatewayService(root_dir=Path(tmp) / "gateway"),
            state_store=SessionEventStore(db_path=Path(tmp) / "state.sqlite3"),
        )
        owner = bridge.upsert_surface_session(
            user_id="owner-1",
            client_label="Owner",
            username="owner_user",
            chat_type="private",
            conversation_id="12345",
            thread_id="thr_owner",
            is_owner=True,
        )
        guest = bridge.upsert_surface_session(
            user_id="guest-1",
            client_label="Guest",
            username="guest_user",
            chat_type="private",
            conversation_id="67890",
            thread_id="thr_guest",
            is_owner=False,
        )
        self.assertEqual(owner["trust_level"], "paired_remote")
        self.assertEqual(guest["trust_level"], "untrusted_remote")

    def test_reply_bundle_adds_research_capsule_and_sources(self) -> None:
        bundle = build_telegram_reply_bundle(
            content="Python 3.13 adds better error messages.",
            route="websearch",
            thread_id="thr_python",
            browse_report={
                "mode": "official",
                "progress_headline": "Checked the official Python docs",
                "sources": [
                    {"title": "What's New In Python 3.13", "url": "https://docs.python.org/3/whatsnew/3.13.html"},
                    {"title": "Python 3.13 release notes", "url": "https://www.python.org/downloads/release/python-3130/"},
                ],
                "sources_count": 2,
            },
        )
        self.assertIn("Research note:", bundle["primary"])
        self.assertIn("Sources:", bundle["primary"])
        self.assertIn("continue", bundle["primary"].lower())


class GenerateResponseAttachmentForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_response_with_attachments_forwards_thread_and_trace_metadata(self) -> None:
        captured: dict[str, object] = {}

        class _DummyAgent:
            def __init__(self) -> None:
                self.user_id = "default_user"
                self.attachments = []

            def _set_last_attachments(self, user_id: str, attachments=None) -> None:
                self.attachments = list(attachments or [])

            def get_last_attachments(self, user_id: str = "default_user"):
                return list(self.attachments)

            async def generate_response(self, **kwargs):
                captured.update(kwargs)
                return "ok"

        agent = _DummyAgent()
        content, attachments = await response_methods.generate_response_with_attachments(
            agent,
            prompt="continue the coding task",
            user_id="user-1",
            thread_id_override="thr_shared",
            trace_metadata={"surface": "telegram", "conversation_id": "12345"},
        )
        self.assertEqual(content, "ok")
        self.assertEqual(attachments, [])
        self.assertEqual(captured.get("thread_id_override"), "thr_shared")
        self.assertEqual(captured.get("trace_metadata"), {"surface": "telegram", "conversation_id": "12345"})


if __name__ == "__main__":
    unittest.main()
