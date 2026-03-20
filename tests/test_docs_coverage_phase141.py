from __future__ import annotations

import re
import unittest
from pathlib import Path

from ops.docs_integrity import REQUIRED_DOC_FILES, run_docs_integrity

ROOT = Path(__file__).resolve().parents[1]


class DocsCoveragePhase141Tests(unittest.TestCase):
    def test_required_readmes_exist_and_have_real_content(self) -> None:
        for relative in REQUIRED_DOC_FILES:
            path = ROOT / relative
            self.assertTrue(path.exists(), relative)
            text = path.read_text(encoding="utf-8")
            self.assertGreaterEqual(len(text.strip().splitlines()), 8, relative)

    def test_docs_integrity_report_is_green_on_repo(self) -> None:
        report = run_docs_integrity(ROOT)
        self.assertTrue(report.get("ok"), report)
        self.assertEqual(list(report.get("missing_files") or []), [])
        self.assertEqual(list(report.get("broken_links") or []), [])

    def test_contributor_map_is_linked_from_core_docs(self) -> None:
        targets = (
            ROOT / "docs" / "architecture" / "README.md",
            ROOT / "README.md",
            ROOT / "workshop" / "README.md",
            ROOT / "gui" / "README.md",
            ROOT / "runtime" / "README.md",
        )
        for path in targets:
            text = path.read_text(encoding="utf-8")
            self.assertIn("CONTRIBUTOR_MAP", text, str(path))

    def test_markdown_file_links_point_to_existing_targets(self) -> None:
        files = [ROOT / relative for relative in REQUIRED_DOC_FILES]
        files.extend(
            [
                ROOT / "docs" / "architecture" / "README.md",
                ROOT / "workshop" / "README.md",
                ROOT / "workshop" / "toolbox" / "README.md",
                ROOT / "gui" / "README.md",
                ROOT / "runtime" / "README.md",
            ]
        )
        pattern = re.compile(r"\[[^\]]+\]\((/C:/somex/[^)]+)\)")
        for path in files:
            text = path.read_text(encoding="utf-8")
            for target in pattern.findall(text):
                target_path = Path(target.replace("/C:/", "C:/"))
                self.assertTrue(target_path.exists(), f"{path}: {target}")


if __name__ == "__main__":
    unittest.main()
