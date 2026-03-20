from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ops.offline_pack_catalog import build_offline_pack_catalog


ROOT = Path(__file__).resolve().parents[1]


class OfflinePackCatalogPhase173Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_offline_catalog_phase173_"))
        pack_dir = self.temp_dir / "knowledge_packs" / "water_basics"
        pack_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": "water_basics",
            "name": "Water Basics",
            "category": "survival",
            "summary": "Purification and storage basics.",
            "tags": ["water", "purify", "storage"],
            "status": "ready",
            "schema_version": 2,
            "variant": "compact",
            "trust": "bundled_local",
            "updated_at": "2026-03-19",
        }
        (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (pack_dir / "water.md").write_text("# Purify water\nFilter and boil water before storage.\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_catalog_surfaces_preferred_variant_and_query_hits(self) -> None:
        report = build_offline_pack_catalog(self.temp_dir, runtime_mode="survival", query="how do i purify water", limit=3)
        self.assertTrue(bool(report.get("ok")))
        self.assertEqual(str(report.get("preferred_variant") or ""), "compact")
        self.assertEqual(int(report.get("pack_count") or 0), 1)
        self.assertTrue(list(report.get("preferred_hits") or []))
        self.assertFalse(list(report.get("fallback_hits") or []))
        self.assertEqual(len(list(report.get("doc_previews") or [])), 1)

    def test_cli_catalog_returns_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "somi.py"),
                "offline",
                "catalog",
                "--json",
                "--root",
                str(self.temp_dir),
                "--runtime-mode",
                "survival",
                "--query",
                "water purification",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"offline catalog CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertEqual(str(payload.get("preferred_variant") or ""), "compact")
        self.assertTrue(list(payload.get("recommended_rows") or []))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
