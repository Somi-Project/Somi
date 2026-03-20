from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gui.controlroom_data import ControlRoomSnapshotBuilder
from ops.doctor import run_somi_doctor
from ops.offline_resilience import run_offline_resilience
from ops.release_gate import build_subsystem_dashboards
from workshop.toolbox.stacks.research_core.local_packs import resolve_local_pack_url, scan_local_packs, search_local_pack_rows


ROOT = Path(__file__).resolve().parents[1]


class OfflineResiliencePhase147Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_offline_phase147_"))
        (self.temp_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database" / "agentpedia" / "pages").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "database").mkdir(exist_ok=True)
        (self.temp_dir / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "release").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / ".venv").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "docs" / "architecture" / "TRUST_BOUNDARIES.md").write_text("# Trust\n", encoding="utf-8")
        checkpoint = self.temp_dir / "audit" / "backups" / "phase147_demo_checkpoint"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "doctor.py").write_text("print('doctor')\n", encoding="utf-8")
        (checkpoint / "docs" / "release").mkdir(parents=True, exist_ok=True)
        (checkpoint / "docs" / "release" / "FRAMEWORK_RELEASE_NOTES.md").write_text("# Update\n", encoding="utf-8")
        (checkpoint / "docs" / "release" / "UPGRADE_PATH_VERIFIED.md").write_text("# Phase\n", encoding="utf-8")

        self._seed_pack(
            "repair_basics",
            "repair",
            ["repair", "generator", "power", "water"],
            "Field repair notes for generator, power, and water diagnostics.",
            "power_and_water.md",
            "# Repair power and water\nCheck generator fuel, spark, filters, and water pump priming.\n",
        )
        self._seed_pack(
            "survival_basics",
            "survival",
            ["survival", "water", "shelter", "sanitation"],
            "Water purification and shelter basics.",
            "water_and_shelter.md",
            "# Purify water and shelter\nFilter sediment before boiling and separate clean storage.\n",
        )
        self._seed_pack(
            "infrastructure_basics",
            "infrastructure",
            ["infrastructure", "communications", "power", "cache"],
            "Communications and power continuity basics.",
            "communications_and_power.md",
            "# Communications continuity\nKeep local cached docs and short structured radio updates.\n",
        )
        (self.temp_dir / "database" / "agentpedia" / "pages" / "water-basics.md").write_text("# Water basics\n", encoding="utf-8")
        evidence_root = self.temp_dir / "state" / "research_cache"
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "demo.json").write_text(json.dumps({"query": "demo"}), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_pack(
        self,
        pack_id: str,
        category: str,
        tags: list[str],
        summary: str,
        doc_name: str,
        doc_text: str,
    ) -> None:
        pack_dir = self.temp_dir / "knowledge_packs" / pack_id
        pack_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": pack_id,
            "name": pack_id.replace("_", " ").title(),
            "category": category,
            "summary": summary,
            "tags": tags,
            "status": "seeded",
            "schema_version": 1,
            "variant": "compact",
            "trust": "bundled_local",
            "updated_at": "2026-03-19",
        }
        (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (pack_dir / doc_name).write_text(doc_text, encoding="utf-8")

    def test_scan_local_packs_reports_required_categories(self) -> None:
        report = scan_local_packs(self.temp_dir)
        self.assertTrue(bool(report.get("ok")))
        self.assertEqual(int(report.get("pack_count") or 0), 3)
        self.assertEqual(sorted(list(report.get("categories_present") or [])), ["infrastructure", "repair", "survival"])
        self.assertEqual(list(report.get("schema_versions") or []), [1])
        self.assertIn("compact", list(report.get("variants_present") or []))
        packs = list(report.get("packs") or [])
        self.assertTrue(packs)
        rows = search_local_pack_rows(self.temp_dir, "how do i purify water offline", limit=3)
        self.assertTrue(rows)
        self.assertEqual(str(rows[0].get("knowledge_origin") or ""), "bundled_local_pack")
        self.assertEqual(str(rows[0].get("pack_variant") or ""), "compact")
        self.assertTrue(str(packs[0].get("integrity") or ""))
        self.assertEqual(len(str(dict(packs[0]).get("documents")[0].get("sha256") or "")), 64)

    def test_resolve_local_pack_url_returns_content_and_integrity(self) -> None:
        rows = search_local_pack_rows(self.temp_dir, "communications continuity", limit=1)
        self.assertTrue(rows)
        resolved = resolve_local_pack_url(self.temp_dir, str(rows[0].get("url") or ""))
        self.assertEqual(str(resolved.get("variant") or ""), "compact")
        self.assertEqual(str(resolved.get("trust") or ""), "bundled_local")
        self.assertIn("Communications continuity", str(resolved.get("content") or ""))
        self.assertEqual(len(str(resolved.get("sha256") or "")), 64)

    def test_run_offline_resilience_counts_local_fallback_assets(self) -> None:
        report = run_offline_resilience(self.temp_dir)
        self.assertTrue(bool(report.get("ok")))
        self.assertEqual(str(report.get("readiness") or ""), "ready")
        self.assertEqual(int(report.get("agentpedia_pages_count") or 0), 1)
        self.assertEqual(int(report.get("evidence_cache_records") or 0), 1)
        self.assertIn("bundled_local_packs", list(report.get("fallback_order") or []))

    def test_doctor_surfaces_offline_resilience(self) -> None:
        report = run_somi_doctor(self.temp_dir)
        self.assertTrue(bool(report.get("ok")))
        offline = dict(report.get("offline_resilience") or {})
        self.assertEqual(str(offline.get("readiness") or ""), "ready")
        self.assertIn("bundled_local_packs", list(offline.get("fallback_order") or []))

    def test_release_gate_dashboards_include_offline_resilience_row(self) -> None:
        offline = run_offline_resilience(self.temp_dir)
        dashboards = build_subsystem_dashboards(
            doctor={"ok": True, "tools": {"available_count": 1, "total": 1}, "applied_repairs": []},
            docs_integrity={"ok": True, "missing_files": [], "broken_links": []},
            artifact_hygiene={"ok": True, "warnings": [], "cleanup_candidates": []},
            offline_resilience=offline,
            security={"ok": True, "summary": {"severity_counts": {}}},
            backups={"verified_count": 5, "recent_count": 5},
            eval_report={"ok": True, "passed": 1, "total": 1},
            replay={"ok": True, "summary": {"issue_count": 0}},
            benchmark_baseline={"packs": []},
            finality_summary={"available": True, "ok": True, "run_id": "demo", "measured_count": 7, "pack_count": 7},
        )
        row = next(item for item in dashboards if str(item.get("id") or "") == "offline_resilience")
        self.assertEqual(str(row.get("status") or ""), "ready")
        self.assertIn("packs=3", str(row.get("subtitle") or ""))

    def test_control_room_observability_rows_include_offline_resilience(self) -> None:
        builder = ControlRoomSnapshotBuilder(
            state_store=Mock(),
            ontology=Mock(),
            memory_manager=Mock(),
            automation_engine=Mock(),
            automation_store=Mock(),
            delivery_gateway=Mock(),
            tool_registry=Mock(),
            subagent_registry=Mock(),
            subagent_status_store=Mock(),
            workflow_store=Mock(),
            workflow_manifest_store=Mock(),
            ops_control=Mock(),
        )
        rows = builder._observability_rows(
            ops_snapshot={"tool_metrics": {}, "model_metrics": {}, "background_tasks": {}, "skill_apprenticeship": {}},
            release_report=None,
            freeze_report=None,
            offline_report=run_offline_resilience(self.temp_dir),
        )
        titles = [str(row.get("title") or "") for row in rows]
        self.assertIn("Offline Resilience", titles)

    def test_offline_status_cli_reports_ready(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "somi.py"), "offline", "status", "--json", "--root", str(self.temp_dir)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"offline status CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertEqual(str(payload.get("readiness") or ""), "ready")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
