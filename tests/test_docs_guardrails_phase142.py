from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ops.doctor import run_somi_doctor
from ops.docs_integrity import CORE_LINK_HOSTS, REQUIRED_DOC_FILES, run_docs_integrity


class DocsGuardrailsPhase142Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_docs_phase142_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / ".venv").mkdir(parents=True, exist_ok=True)
        checkpoint = self.temp_dir / "audit" / "backups" / "phase142_demo"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "update.md").write_text("# update\n", encoding="utf-8")
        (checkpoint / "phase_upgrade.md").write_text("# phase\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_valid_docs(self) -> None:
        for relative in REQUIRED_DOC_FILES:
            path = self.temp_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(
                    [
                        "# doc",
                        "",
                        "See [`README.md`](/C:/somex/README.md) for context.",
                        "Line 4",
                        "Line 5",
                        "Line 6",
                        "Line 7",
                        "Line 8",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        (self.temp_dir / "README.md").write_text("# root\nCONTRIBUTOR_MAP\n", encoding="utf-8")
        for relative in CORE_LINK_HOSTS:
            path = self.temp_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("CONTRIBUTOR_MAP\n", encoding="utf-8")

    def test_docs_integrity_passes_when_required_files_and_links_exist(self) -> None:
        self._write_valid_docs()
        report = run_docs_integrity(self.temp_dir)
        self.assertTrue(report.get("ok"), report)

    def test_doctor_flags_docs_integrity_gaps(self) -> None:
        report = run_somi_doctor(self.temp_dir)
        self.assertFalse(bool(dict(report.get("docs_integrity") or {}).get("ok", True)))
        titles = [str(item.get("title") or "") for item in list(report.get("issues") or [])]
        self.assertIn("Contributor documentation has missing or stale checkpoints", titles)


if __name__ == "__main__":
    unittest.main()
