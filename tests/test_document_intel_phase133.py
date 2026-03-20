from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.stacks.ocr_core.document_intel import (
    build_document_note,
    extract_document_payload,
)


class DocumentIntelPhase133Tests(unittest.TestCase):
    def test_extract_text_document_cleans_excerpt_and_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("  Build plan  \n\n\nStep 1: Inspect logs\nStep 2: Patch runtime  ", encoding="utf-8")
            payload = extract_document_payload(path)
            self.assertTrue(payload["ok"])
            self.assertIn("Build plan", payload["excerpt"])
            self.assertTrue(payload["anchors"])
            self.assertEqual(payload["document_kind"], "text")

    def test_extract_csv_document_builds_row_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invoice.csv"
            path.write_text("item,qty,total\nGPU Fan,2,31.00\nThermal Paste,1,5.00\n", encoding="utf-8")
            payload = extract_document_payload(path)
            self.assertTrue(payload["ok"])
            self.assertIn("item | qty | total", payload["excerpt"])
            self.assertEqual(payload["anchors"][0]["label"], "row1")

    def test_unsupported_document_requests_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.zip"
            path.write_bytes(b"PK\x03\x04")
            payload = extract_document_payload(path)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["manual_review_required"])
            self.assertIn("Supported uploads", payload["manual_review_message"])

    def test_document_note_surfaces_provenance_and_anchors(self) -> None:
        note = build_document_note(
            {
                "file_name": "report.pdf",
                "document_kind": "pdf",
                "page_count": 3,
                "excerpt": "Important findings go here.",
                "anchors": [
                    {"label": "p1", "snippet": "Executive summary"},
                    {"label": "p2", "snippet": "Repair priorities"},
                ],
            }
        )
        self.assertIn("File: report.pdf", note)
        self.assertIn("Anchors:", note)
        self.assertIn("p1", note)


if __name__ == "__main__":
    unittest.main()
