from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_release_candidate_specs(prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "researchhard100",
            "label": "Research Hard 100",
            "kind": "search_batch",
            "corpus": "researchhard100",
            "chunk_size": 10,
            "somi_timeout": 35.0,
            "prefix": f"{prefix}_researchhard100",
        },
        {
            "id": "coding_suite",
            "label": "Coding Runtime Suite",
            "kind": "unittest",
            "tests": [
                str(ROOT / "tests" / "test_codex_control_phase119.py"),
                str(ROOT / "tests" / "test_coding_compaction_phase130.py"),
            ],
        },
        {
            "id": "memory_suite",
            "label": "Memory Continuity Suite",
            "kind": "unittest",
            "tests": [
                str(ROOT / "tests" / "test_memory_session_search_phase7.py"),
                str(ROOT / "executive" / "memory" / "tests" / "test_preference_graph.py"),
            ],
        },
        {
            "id": "telegram_suite",
            "label": "Telegram Parity Suite",
            "kind": "unittest",
            "tests": [
                str(ROOT / "tests" / "test_telegram_runtime_phase132.py"),
                str(ROOT / "tests" / "test_document_intel_phase133.py"),
            ],
        },
    ]


def _run_unittest_pack(spec: dict[str, Any], *, python_executable: Path) -> dict[str, Any]:
    tests = [str(item) for item in list(spec.get("tests") or []) if str(item).strip()]
    cmd = [str(python_executable), "-m", "unittest", *tests, "-v"]
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    seconds = round(time.perf_counter() - started, 2)
    return {
        "id": str(spec.get("id") or ""),
        "label": str(spec.get("label") or ""),
        "kind": "unittest",
        "status": "pass" if proc.returncode == 0 else "fail",
        "ok": proc.returncode == 0,
        "seconds": seconds,
        "command": cmd,
        "artifacts": {},
        "details": {
            "stdout_tail": str(proc.stdout or "").splitlines()[-20:],
            "stderr_tail": str(proc.stderr or "").splitlines()[-20:],
        },
    }


def _run_search_pack(spec: dict[str, Any], *, python_executable: Path, output_dir: Path) -> dict[str, Any]:
    prefix = str(spec.get("prefix") or spec.get("id") or "release_candidate").strip()
    manifest_path = output_dir / f"{prefix}_manifest.json"
    cmd = [
        str(python_executable),
        str(ROOT / "audit" / "search_benchmark_batch.py"),
        "--corpus",
        str(spec.get("corpus") or "researchhard100"),
        "--chunk-size",
        str(int(spec.get("chunk_size") or 10)),
        "--output-dir",
        str(output_dir),
        "--prefix",
        prefix,
        "--somi-timeout",
        str(float(spec.get("somi_timeout") or 35.0)),
    ]
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=7200)
    seconds = round(time.perf_counter() - started, 2)
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            manifest = {}
    combined_paths = dict(manifest.get("combined_paths") or {})
    return {
        "id": str(spec.get("id") or ""),
        "label": str(spec.get("label") or ""),
        "kind": "search_batch",
        "status": "pass" if proc.returncode == 0 else "fail",
        "ok": proc.returncode == 0,
        "seconds": seconds,
        "command": cmd,
        "artifacts": combined_paths,
        "details": {
            "stdout_tail": str(proc.stdout or "").splitlines()[-20:],
            "stderr_tail": str(proc.stderr or "").splitlines()[-20:],
            "manifest_path": str(manifest_path),
            "stabilized_cases": len(list(manifest.get("stabilized_cases") or [])),
            "chunk_statuses": [str(item.get("status") or "") for item in list(manifest.get("chunks") or [])],
        },
    }


def build_release_candidate_report(
    *,
    python_executable: Path,
    output_dir: Path,
    prefix: str,
    selected_packs: list[str] | None = None,
) -> dict[str, Any]:
    specs = build_release_candidate_specs(prefix)
    selected = {item.strip().lower() for item in list(selected_packs or []) if str(item).strip()}
    if selected:
        specs = [spec for spec in specs if str(spec.get("id") or "").lower() in selected]

    packs: list[dict[str, Any]] = []
    for spec in specs:
        if spec.get("kind") == "search_batch":
            packs.append(_run_search_pack(spec, python_executable=python_executable, output_dir=output_dir))
        else:
            packs.append(_run_unittest_pack(spec, python_executable=python_executable))

    ok = all(bool(pack.get("ok")) for pack in packs)
    return {
        "generated_at": _now_iso(),
        "prefix": prefix,
        "ok": ok,
        "status": "pass" if ok else "fail",
        "pack_count": len(packs),
        "packs": packs,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release Candidate",
        "",
        f"Generated: {report.get('generated_at', '')}",
        f"Status: {report.get('status', '')}",
        f"Pack count: {report.get('pack_count', 0)}",
        "",
    ]
    for pack in list(report.get("packs") or []):
        lines.append(f"## {pack.get('label', '')}")
        lines.append("")
        lines.append(f"- Status: {pack.get('status', '')}")
        lines.append(f"- Seconds: {pack.get('seconds', 0)}")
        lines.append(f"- Kind: {pack.get('kind', '')}")
        if dict(pack.get("artifacts") or {}):
            lines.append(f"- Artifacts: {dict(pack.get('artifacts') or {})}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_release_candidate_report(
    *,
    root_dir: str | Path = ".",
    python_executable: str = sys.executable,
    output_dir: str | Path = "audit",
    prefix: str = "release_candidate",
    selected_packs: list[str] | None = None,
) -> dict[str, Any]:
    del root_dir
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = build_release_candidate_report(
        python_executable=Path(python_executable),
        output_dir=out,
        prefix=prefix,
        selected_packs=selected_packs,
    )
    json_path = out / f"{prefix}.json"
    md_path = out / f"{prefix}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    persisted = dict(report)
    persisted["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return persisted


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a release-candidate validation pack across search and runtime suites.")
    parser.add_argument("--output-dir", default=str(ROOT / "audit"), help="Directory for release-candidate artifacts.")
    parser.add_argument("--prefix", default="release_candidate", help="Artifact prefix.")
    parser.add_argument("--python-executable", default=sys.executable, help="Python interpreter to use.")
    parser.add_argument("--packs", default="", help="Comma-separated pack ids to run. Defaults to all.")
    args = parser.parse_args()

    selected = [item.strip() for item in str(args.packs or "").split(",") if item.strip()]
    report = write_release_candidate_report(
        output_dir=args.output_dir,
        prefix=str(args.prefix or "release_candidate"),
        python_executable=str(args.python_executable or sys.executable),
        selected_packs=selected,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
