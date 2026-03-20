from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audit.system_gauntlet import _run_search_pack, build_system_gauntlet_specs, write_system_gauntlet_report


class SystemGauntletPhase136Tests(unittest.TestCase):
    def test_default_specs_cover_all_full_system_packs(self) -> None:
        specs = build_system_gauntlet_specs("phase136_test")
        ids = {str(spec.get("id") or "") for spec in specs}
        self.assertEqual(
            ids,
            {"search100", "memory100", "reminder100", "compaction100", "ocr100", "coding100", "averageuser30"},
        )

    def test_report_writer_runs_subset_without_live_search(self) -> None:
        with tempfile.TemporaryDirectory(prefix="somi_phase136_subset_") as tmp:
            report = write_system_gauntlet_report(
                output_dir=tmp,
                prefix="phase136_subset",
                selected_packs=["memory100", "reminder100", "compaction100", "ocr100", "coding100", "averageuser30"],
                base_count=12,
                scenario_turns=12,
                include_live_chat=False,
            )
            self.assertTrue(report.get("ok"))
            self.assertEqual(int(report.get("pack_count") or 0), 6)
            self.assertTrue(Path(str(report["paths"]["json"])).exists())
            self.assertTrue(Path(str(report["paths"]["markdown"])).exists())

    def test_cli_subset_runs_through_release_gauntlet_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="somi_phase136_cli_") as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "C:\\somex\\somi.py",
                    "release",
                    "gauntlet",
                    "--json",
                    "--root",
                    "C:\\somex",
                    "--prefix",
                    "phase136_cli_subset",
                    "--output-dir",
                    tmp,
                    "--packs",
                    "memory100,ocr100",
                    "--count",
                    "8",
                    "--scenario-turns",
                    "8",
                    "--skip-live-chat",
                ],
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            if result.returncode != 0:
                self.fail(f"gauntlet CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
            payload = json.loads(result.stdout.strip())
            self.assertTrue(payload.get("ok"))
            self.assertEqual(int(payload.get("pack_count") or 0), 2)

    def test_search_pack_forwards_limit_to_batch_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="somi_phase136_limit_") as tmp:
            output_dir = Path(tmp)
            seen: dict[str, object] = {}

            def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                seen["cmd"] = list(cmd)
                prefix = "phase136_limit"
                combined_jsonl = output_dir / f"{prefix}_combined.jsonl"
                combined_report = output_dir / f"{prefix}_combined.md"
                combined_summary = output_dir / f"{prefix}_combined_summary.md"
                manifest_path = output_dir / f"{prefix}_manifest.json"
                combined_jsonl.write_text("\n".join('{"query":"q"}' for _ in range(12)) + "\n", encoding="utf-8")
                combined_report.write_text("# report\n", encoding="utf-8")
                combined_summary.write_text("# summary\n", encoding="utf-8")
                manifest_path.write_text(
                    json.dumps(
                        {
                            "corpus": "everyday100",
                            "limit": 12,
                            "chunk_size": 10,
                            "start_chunk": 0,
                            "end_chunk": 1,
                            "total_cases": 12,
                            "total_chunks": 2,
                            "combined_paths": {
                                "jsonl": str(combined_jsonl),
                                "report": str(combined_report),
                                "summary": str(combined_summary),
                            },
                            "stabilized_cases": [],
                            "chunks": [{"chunk_index": 0, "status": "ok", "rows": 12}],
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            with patch("audit.system_gauntlet._run_command", side_effect=_fake_run_command):
                result = _run_search_pack(
                    {
                        "id": "search100",
                        "label": "Search 100",
                        "corpus": "everyday100",
                        "chunk_size": 10,
                        "somi_timeout": 10.0,
                        "prefix": "phase136_limit",
                        "count": 12,
                    },
                    python_executable=Path(sys.executable),
                    output_dir=output_dir,
                )
            cmd = list(seen.get("cmd") or [])
            self.assertIn("--limit", cmd)
            self.assertIn("12", cmd)
            self.assertTrue(result.get("ok"))
            self.assertEqual(int(dict(result.get("counts") or {}).get("target") or 0), 12)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
