from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.qt import QApplication, QFrame, QPushButton
from somicontroller import SomiAIGUI


class GuiShellRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_window(self) -> SomiAIGUI:
        window = SomiAIGUI()
        window.show()
        for _ in range(4):
            self._app.processEvents()
        return window

    def _spin_until(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.time() + max(0.1, timeout)
        while time.time() < deadline:
            self._app.processEvents()
            if predicate():
                return True
            time.sleep(0.05)
        self._app.processEvents()
        return bool(predicate())

    def _dispose_window(self, window: SomiAIGUI) -> None:
        try:
            window.stop_chat_worker()
        except Exception:
            pass
        try:
            window.heartbeat_service.stop()
        except Exception:
            pass
        try:
            window.close()
        except Exception:
            pass
        self._app.processEvents()

    def test_main_window_exposes_clustered_cockpit_and_live_research_pulse(self) -> None:
        window = self._build_window()
        try:
            self.assertIsNotNone(window.findChild(QFrame, "personaCluster"))
            self.assertIsNotNone(window.findChild(QFrame, "cabinCluster"))
            self.assertIsNotNone(window.findChild(QFrame, "studioCluster"))
            self.assertIsNotNone(window.findChild(QFrame, "opsCluster"))
            self.assertIsNotNone(window.findChild(QFrame, "heartbeatCluster"))
            self.assertEqual(window.theme_mode_caption.text().strip(), window._theme_mode_emoji(window.read_gui_settings().get("theme")))
            self.assertEqual(window.chips_label.objectName(), "heroSubline")
            self.assertFalse(window.chips_label.wordWrap())

            action_labels = [
                btn.text()
                for btn in window.findChildren(QPushButton)
                if btn.objectName() == "quickActionButton"
            ]
            self.assertIn("Talk", action_labels)
            self.assertIn("Research", action_labels)
            self.assertIn("Agentpedia", action_labels)
            self.assertIn("HB Resume", action_labels)

            window.update_research_pulse(
                {
                    "query": "latest hypertension guidelines",
                    "mode": "official",
                    "summary": "Pulled official guidance and condensed it into a clean answer.",
                    "trace": ["plan -> official shortlist", "compose -> premium answer"],
                    "execution_events": [
                        {"label": "search", "detail": "official shortlist ready", "status": "working"},
                        {"label": "open", "detail": "adequacy check passed", "status": "done"},
                    ],
                    "sources": [
                        "https://www.acc.org/latest-in-cardiology/articles/2025/08/14/high-blood-pressure-guideline",
                        "https://www.heart.org/en/health-topics/high-blood-pressure",
                    ],
                    "sources_count": 4,
                    "limitations_count": 1,
                    "updated_at": "20:02",
                },
                announce=False,
            )
            self._app.processEvents()
            self.assertEqual(window.research_mode_label.text(), "OFFICIAL | 4 src")
            self.assertIn("latest hypertension guidelines", window.research_query_label.text())
            self.assertIn("Pulled official guidance", window.research_summary_label.text())
            self.assertIn("official shortlist", window.research_trace_label.text())
            self.assertIsNotNone(window.research_feed_list)
            self.assertGreaterEqual(window.research_feed_list.count(), 4)
            self.assertIn("LIVE | search -> official shortlist ready", window.research_feed_list.item(0).text())
            self.assertIn("DONE | open -> adequacy check passed", window.research_feed_list.item(1).text())
            self.assertIn("acc.org/latest-in-cardiology/articles/2025/08/14/high-blood-pressure-guideline", window.research_feed_list.item(2).text())
            self.assertIn("Latest browse pulse", window.research_studio_panel.active_detail_label.text())
            self.assertIn("acc.org/latest-in-cardiology", window.research_studio_panel.active_memory_label.text())
            self.assertIn("Timeline:", window.research_studio_panel.subagent_label.text())
            self.assertIsNotNone(window.research_signal_meter)
            self.assertEqual(window.research_signal_meter._mode, "official")
            self.assertEqual(window.research_signal_meter._sources_count, 4)
            self.assertEqual(window.research_signal_meter._limitations_count, 1)
            self.assertIn("Browse OFFICIAL/4", window.metrics_label.text())
        finally:
            self._dispose_window(window)

    def test_startup_preloads_chat_worker_without_worker_error_banner(self) -> None:
        window = self._build_window()
        try:
            warmed = self._spin_until(
                lambda: bool(
                    getattr(window, "chat_worker", None)
                    and window.chat_worker.isRunning()
                ),
                timeout=2.5,
            )
            self.assertTrue(warmed, "chat worker should start pre-initializing shortly after startup")
            transcript = window.chat_panel.chat_area.toPlainText()
            self.assertNotIn("Chat worker not running or agent not initialized.", transcript)
            self.assertNotIn("Chat worker online", transcript)
            self.assertIn("Status:", window.chat_panel.status_label.text())
        finally:
            self._dispose_window(window)

    def test_ops_stream_uses_single_combined_card_and_compact_chat_controls(self) -> None:
        window = self._build_window()
        try:
            self.assertIs(window.command_stream_card, window.intel_card)
            self.assertIs(window.heartbeat_stream_list.parentWidget(), window.intel_card)
            self.assertEqual(window.intel_title.text(), "Ops Stream")
            self.assertFalse(window.chat_panel.send_button.autoDefault())
            self.assertFalse(window.chat_panel.send_button.isDefault())
            self.assertFalse(window.chat_panel.upload_image_button.autoDefault())
            self.assertFalse(window.chat_panel.upload_image_button.isDefault())
            speech_card = window.findChild(QFrame, "speechCard")
            self.assertIsNotNone(speech_card)
            self.assertLessEqual(speech_card.maximumHeight(), 118)
            window._rebalance_core_splitter()
            self._app.processEvents()
            left_size, right_size = window.core_splitter.sizes()[:2]
            self.assertGreater(left_size, right_size)
            self.assertLessEqual(window.tabs.maximumHeight(), max(190, int(window.height() * 0.28)))
        finally:
            self._dispose_window(window)

    def test_research_pulse_falls_back_to_progress_headline_and_human_meta_copy(self) -> None:
        window = self._build_window()
        try:
            window.update_research_pulse(
                {
                    "query": "compare kindle paperwhite and kobo clara",
                    "mode": "deep",
                    "summary": "",
                    "progress_headline": "Read -> comparison shortlist gathered from trusted review sources",
                    "sources_count": 3,
                    "limitations_count": 2,
                    "updated_at": "20:14",
                },
                announce=False,
            )
            self._app.processEvents()
            self.assertIn("comparison shortlist gathered", window.research_summary_label.text())
            self.assertTrue(window.research_trace_label.isHidden() or not window.research_trace_label.text().strip())
            self.assertEqual(window.research_meta_label.text(), "Updated 20:14 | cautions 2")
        finally:
            self._dispose_window(window)

    def test_research_pulse_meta_surfaces_trust_when_report_provides_it(self) -> None:
        window = self._build_window()
        try:
            window.update_research_pulse(
                {
                    "query": "latest dengue guidance",
                    "mode": "official",
                    "summary": "Checked the current WHO publication set.",
                    "trust_level": "high",
                    "trust_summary": "Trust HIGH: multiple corroborating sources support this answer.",
                    "sources_count": 3,
                    "limitations_count": 1,
                    "updated_at": "20:22",
                },
                announce=False,
            )
            self._app.processEvents()
            self.assertEqual(window.research_meta_label.text(), "Updated 20:22 | trust HIGH | cautions 1")
            self.assertIn("current WHO publication set", window.research_summary_label.text())
        finally:
            self._dispose_window(window)


if __name__ == "__main__":
    unittest.main()
