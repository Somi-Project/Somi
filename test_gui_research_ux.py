from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.aicoregui import _compact_research_report
from gui.chatpanel import _render_research_capsule
from gui.qt import QApplication
from gui.researchstudio import ResearchStudioPanel


class GuiResearchUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_compact_research_report_keeps_core_trace_fields(self) -> None:
        report = _compact_research_report(
            {
                "query": "check out openclaw on github",
                "mode": "github",
                "summary": "OpenClaw is a GitHub repository with a verified README and manifests.",
                "progress_headline": "1. Route -> github repo inspection",
                "trust_level": "high",
                "trust_summary": "Trust HIGH: multiple corroborating sources support this answer.",
                "validator_issue_count": 0,
                "execution_steps": [
                    "plan: mode=github",
                    "read: inspected README and manifests for 1 repo(s)",
                ],
                "sources": [
                    "https://github.com/openclaw/openclaw",
                    "https://github.com/openclaw/openclaw/blob/main/README.md",
                ],
                "limitations": ["Temporary repository clone cleaned up after inspection."],
            }
        )
        self.assertEqual(report["mode"], "github")
        self.assertEqual(report["sources_count"], 2)
        self.assertEqual(report["limitations_count"], 1)
        self.assertEqual(report["trust_level"], "high")
        self.assertIn("Trust HIGH", report["trust_summary"])
        self.assertTrue(report["trace"])
        self.assertTrue(report["timeline"])
        self.assertIn("github.com/openclaw/openclaw", report["source_preview"][0])

    def test_render_research_capsule_is_compact_and_human(self) -> None:
        capsule = _render_research_capsule(
            {
                "mode": "deep",
                "sources_count": 4,
                "trust_level": "solid",
                "progress_headline": "1. Read -> opened the latest WHO guidance page and extracted dates",
                "limitations_count": 1,
            }
        )
        self.assertIn("Deep browse", capsule)
        self.assertIn("4 sources", capsule)
        self.assertIn("trust SOLID", capsule)
        self.assertIn("Read -> opened the latest WHO guidance page", capsule)
        self.assertIn("1 caution", capsule)

    def test_research_studio_panel_uses_latest_browse_pulse_without_explicit_builder(self) -> None:
        class DummyController:
            def __init__(self) -> None:
                self.state = {
                    "research_pulse": {
                        "mode": "deep_browse",
                        "query": "latest hypertension guidelines",
                        "summary": "Pulled AHA/ACC guidance and supporting sources.",
                        "trace": ["search -> official shortlist", "open -> adequacy check"],
                        "timeline": ["LIVE | search -> official shortlist", "DONE | open -> adequacy check"],
                        "source_preview": ["acc.org/latest-hypertension-guideline", "heart.org/high-blood-pressure"],
                    }
                }

        panel = ResearchStudioPanel(controller=DummyController())
        try:
            panel.refresh_data()
            self.assertIn("Latest browse pulse", panel.active_detail_label.text())
            self.assertIn("hypertension guidelines", panel.active_detail_label.text())
            self.assertIn("Pulled AHA/ACC guidance", panel.active_memory_label.text())
            self.assertIn("acc.org", panel.active_memory_label.text())
            self.assertIn("search -> official shortlist", panel.subagent_label.text())
            self.assertIn("Timeline:", panel.subagent_label.text())
            self.assertIn("LIVE | search -> official shortlist", panel.subagent_label.text())
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main()
