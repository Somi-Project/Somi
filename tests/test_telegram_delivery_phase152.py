from __future__ import annotations

import os
import unittest
from pathlib import Path

from workshop.integrations.telegram_runtime import build_telegram_delivery_bundle


class TelegramDeliveryPhase152Tests(unittest.TestCase):
    def test_long_coding_bundle_creates_export_document(self) -> None:
        bundle = build_telegram_delivery_bundle(
            content=("Implement the repair workflow and verify each step. " * 140).strip(),
            route="coding_mode",
            thread_id="thr_repair",
            task_id="task-1234567890",
        )
        exports = list(bundle.get("exports") or [])
        self.assertEqual(len(exports), 1)
        export = exports[0]
        export_path = Path(str(export.get("path") or ""))
        self.addCleanup(lambda: export_path.exists() and export_path.unlink())
        self.assertTrue(export_path.exists())
        self.assertIn("attached the full write-up", str(bundle.get("primary") or "").lower())
        exported_text = export_path.read_text(encoding="utf-8")
        self.assertIn("# Somi Telegram Export", exported_text)
        self.assertIn("## Response", exported_text)
        self.assertIn("coding_mode", exported_text)

    def test_document_bundle_surfaces_capsule_sources_and_resume_note(self) -> None:
        bundle = build_telegram_delivery_bundle(
            content="Here is the document summary with the repair priorities.",
            route="websearch",
            thread_id="thr_doc",
            task_id="task-doc-42",
            document_payload={
                "file_name": "repair-report.pdf",
                "document_kind": "pdf",
                "page_count": 3,
                "anchors": [
                    {"label": "p1", "snippet": "Executive summary"},
                    {"label": "p2", "snippet": "Repair priorities"},
                ],
            },
            document_note=(
                "Document note: File: repair-report.pdf | Type: pdf | Pages: 3\n"
                "Anchors:\n- p1: Executive summary\n- p2: Repair priorities"
            ),
            browse_report={
                "mode": "official",
                "progress_headline": "Checked the official repair manual",
                "sources": [
                    {"title": "Repair manual", "url": "https://example.com/manual"},
                    {"title": "Safety notes", "url": "https://example.com/safety"},
                ],
            },
            continuity_report={
                "surface_names": ["telegram", "gui"],
                "open_task_count": 2,
                "recommended_surface": "gui",
                "last_route": "websearch",
                "resume_hint": "Resume on the GUI to keep reading the detailed handoff.",
            },
            create_exports=False,
        )
        mixed = "\n\n".join([str(bundle.get("primary") or "")] + [str(item) for item in list(bundle.get("follow_ups") or [])])
        self.assertIn("repair-report.pdf", mixed)
        self.assertIn("Sources:", mixed)
        self.assertIn("Task note:", mixed)
        self.assertIn("Continuity note:", mixed)
        self.assertIn("best next surface gui", mixed.lower())
        self.assertIn("Resume on the GUI", mixed)
        self.assertIn("anchors p1, p2", mixed.lower())
        self.assertEqual(bundle.get("source_preview"), ["Repair manual", "Safety notes"])


if __name__ == "__main__":
    unittest.main()
