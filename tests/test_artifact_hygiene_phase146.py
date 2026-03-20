from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ops.artifact_hygiene import ArtifactPolicy, run_artifact_hygiene
from ops.release_gate import _collect_blockers, build_subsystem_dashboards


class ArtifactHygienePhase146Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_artifacts_phase146_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_artifact_hygiene_flags_over_budget_and_collects_stale_candidates(self) -> None:
        audit_dir = self.temp_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        old_file = audit_dir / "phase100_old.jsonl"
        old_file.write_text("row\n", encoding="utf-8")
        now = old_file.stat().st_mtime
        os.utime(old_file, (now - 5 * 24 * 3600, now - 5 * 24 * 3600))
        (audit_dir / "phase101_new.md").write_text("# New\n", encoding="utf-8")

        policy = ArtifactPolicy(
            name="audit_test",
            relative_path="audit",
            max_files=1,
            max_megabytes=0.000001,
            stale_days=1,
            include_suffixes=(".jsonl", ".md"),
        )
        report = run_artifact_hygiene(self.temp_dir, policies=(policy,))

        self.assertFalse(bool(report.get("ok")))
        self.assertEqual(len(list(report.get("warnings") or [])), 2)
        candidate = list(report.get("cleanup_candidates") or [])[0]
        self.assertEqual(candidate.get("scope"), "audit_test")
        self.assertTrue(str(candidate.get("path") or "").endswith("phase100_old.jsonl"))

    def test_release_gate_helpers_surface_artifact_hygiene_row_and_warning(self) -> None:
        artifact_hygiene = {
            "ok": False,
            "warnings": ["audit_generated has too many files."],
            "cleanup_candidates": [{"scope": "audit_generated", "path": "C:/somex/audit/old.jsonl"}],
        }
        blockers, warnings = _collect_blockers(
            doctor={"ok": True},
            docs_integrity={"ok": True},
            artifact_hygiene=artifact_hygiene,
            offline_resilience={"ok": True, "readiness": "ready", "missing_categories": [], "fallback_order": ["bundled_local_packs"]},
            security={"ok": True, "summary": {"severity_counts": {}}},
            backups={"verified_count": 5},
            eval_report={"ok": True},
            replay={"ok": True},
            benchmark_baseline={"packs": []},
        )
        self.assertEqual(blockers, [])
        self.assertTrue(any(str(row.get("type") or "") == "artifacts" for row in warnings))

        dashboards = build_subsystem_dashboards(
            doctor={"ok": True, "tools": {"available_count": 1, "total": 1}, "applied_repairs": []},
            docs_integrity={"ok": True, "missing_files": [], "broken_links": []},
            artifact_hygiene=artifact_hygiene,
            offline_resilience={"ok": True, "readiness": "ready", "knowledge_packs": {"pack_count": 3}, "agentpedia_pages_count": 2, "evidence_cache_records": 4},
            security={"ok": True, "summary": {"severity_counts": {}}},
            backups={"verified_count": 5, "recent_count": 5},
            eval_report={"ok": True, "passed": 1, "total": 1},
            replay={"ok": True, "summary": {"issue_count": 0}},
            benchmark_baseline={"packs": []},
            finality_summary={"available": True, "ok": True, "run_id": "demo", "measured_count": 7, "pack_count": 7},
        )
        artifact_row = next(row for row in dashboards if str(row.get("id") or "") == "artifacts")
        self.assertEqual(artifact_row.get("status"), "warn")
        self.assertIn("warnings=1", str(artifact_row.get("subtitle") or ""))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
