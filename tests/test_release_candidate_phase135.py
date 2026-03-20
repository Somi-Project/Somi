from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from audit.release_candidate import build_release_candidate_specs, write_release_candidate_report


class ReleaseCandidatePhase135Tests(unittest.TestCase):
    def test_default_specs_include_search_coding_memory_and_telegram(self) -> None:
        specs = build_release_candidate_specs("phase135")
        ids = {str(item.get("id") or "") for item in specs}
        self.assertEqual(ids, {"researchhard100", "coding_suite", "memory_suite", "telegram_suite"})

    def test_report_writer_can_run_subset_without_search_pack(self) -> None:
        with tempfile.TemporaryDirectory(prefix="somi_rc_phase135_") as tmp:
            report = write_release_candidate_report(
                output_dir=tmp,
                prefix="phase135_subset",
                selected_packs=["memory_suite", "telegram_suite"],
            )
            self.assertTrue(bool(report.get("ok")))
            self.assertTrue(Path(str(dict(report.get("paths") or {}).get("json") or "")).exists())
            self.assertTrue(Path(str(dict(report.get("paths") or {}).get("markdown") or "")).exists())
            self.assertEqual(len(list(report.get("packs") or [])), 2)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
