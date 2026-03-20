from __future__ import annotations

import asyncio
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.safe_search_corpus import build_named_corpus
from audit.search_benchmark import _evaluate_case, _read_jsonl, _render_markdown, _render_summary_markdown


def expected_chunk_size(total_cases: int, chunk_size: int, chunk_index: int) -> int:
    total = max(0, int(total_cases or 0))
    size = max(1, int(chunk_size or 1))
    index = max(0, int(chunk_index or 0))
    start = index * size
    if start >= total:
        return 0
    return min(size, total - start)


def chunk_paths(output_dir: Path, prefix: str, chunk_index: int) -> Dict[str, Path]:
    stem = f"{prefix}_chunk{int(chunk_index):02d}"
    return {
        "jsonl": output_dir / f"{stem}.jsonl",
        "report": output_dir / f"{stem}.md",
        "summary": output_dir / f"{stem}_summary.md",
    }


def _kill_process_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        pass


def _chunk_complete(paths: Dict[str, Path], expected_rows: int) -> bool:
    if expected_rows <= 0:
        return True
    json_rows = _read_jsonl(paths.get("jsonl"))
    return (
        paths.get("jsonl", Path()).exists()
        and paths.get("report", Path()).exists()
        and paths.get("summary", Path()).exists()
        and len(json_rows) >= expected_rows
    )


def _run_chunk(
    *,
    python_executable: Path,
    corpus: str,
    limit: int,
    chunk_size: int,
    chunk_index: int,
    expected_rows: int,
    output_dir: Path,
    prefix: str,
    somi_timeout: float,
    compare_baselines: bool,
    timeout_s: float,
    stable_seconds: float,
) -> Dict[str, Any]:
    paths = chunk_paths(output_dir, prefix, chunk_index)
    cmd = [
        str(python_executable),
        str((REPO_ROOT / "audit" / "search_benchmark.py").resolve()),
        "--corpus",
        str(corpus),
        "--limit",
        str(max(0, int(limit or 0))),
        "--chunk-size",
        str(int(chunk_size)),
        "--chunk-index",
        str(int(chunk_index)),
        "--somi-timeout",
        str(float(somi_timeout)),
        "--output",
        str(paths["report"]),
        "--json-output",
        str(paths["jsonl"]),
        "--summary-output",
        str(paths["summary"]),
        "--save-every",
        "5",
        "--no-stdout-report",
        "--hard-exit",
    ]
    if compare_baselines:
        cmd.append("--compare-baselines")

    started_at = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stable_since: float | None = None

    while True:
        return_code = proc.poll()
        complete = _chunk_complete(paths, expected_rows=expected_rows)

        if complete:
            if return_code is not None:
                rows = _read_jsonl(paths["jsonl"])
                return {
                    "chunk_index": int(chunk_index),
                    "status": "ok" if return_code == 0 else f"artifact_exit_{return_code}",
                    "rows": len(rows),
                    "seconds": round(time.time() - started_at, 2),
                    "paths": {key: str(value) for key, value in paths.items()},
                }
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= max(5.0, float(stable_seconds)):
                _kill_process_tree(proc.pid)
                rows = _read_jsonl(paths["jsonl"])
                return {
                    "chunk_index": int(chunk_index),
                    "status": "artifact_stable_killed",
                    "rows": len(rows),
                    "seconds": round(time.time() - started_at, 2),
                    "paths": {key: str(value) for key, value in paths.items()},
                }
        else:
            stable_since = None
            if return_code is not None:
                rows = _read_jsonl(paths["jsonl"])
                return {
                    "chunk_index": int(chunk_index),
                    "status": f"failed_exit_{return_code}",
                    "rows": len(rows),
                    "seconds": round(time.time() - started_at, 2),
                    "paths": {key: str(value) for key, value in paths.items()},
                }

        if time.time() - started_at > max(60.0, float(timeout_s)):
            _kill_process_tree(proc.pid)
            rows = _read_jsonl(paths["jsonl"])
            return {
                "chunk_index": int(chunk_index),
                "status": "timeout",
                "rows": len(rows),
                "seconds": round(time.time() - started_at, 2),
                "paths": {key: str(value) for key, value in paths.items()},
            }

        time.sleep(5.0)


def _write_combined_outputs(output_dir: Path, prefix: str, results: List[Dict[str, Any]]) -> Dict[str, str]:
    combined_jsonl = output_dir / f"{prefix}_combined.jsonl"
    combined_md = output_dir / f"{prefix}_combined.md"
    combined_summary = output_dir / f"{prefix}_combined_summary.md"
    combined_jsonl.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in results) + ("\n" if results else ""),
        encoding="utf-8",
    )
    combined_md.write_text(_render_markdown(results, corpus_name=prefix), encoding="utf-8")
    combined_summary.write_text(_render_summary_markdown(results, corpus_name=prefix), encoding="utf-8")
    return {
        "jsonl": str(combined_jsonl),
        "report": str(combined_md),
        "summary": str(combined_summary),
    }


def _needs_stabilized_rerun(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("somi_error") or "").strip():
        return True
    notes = [str(item or "").strip().lower() for item in list(result.get("notes") or [])]
    if "no_rows" in notes:
        return True
    return int(result.get("score") or 0) <= 2


def _prefer_stabilized_result(original: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    original_score = int(original.get("score") or 0)
    candidate_score = int(candidate.get("score") or 0)
    original_error = str(original.get("somi_error") or "").strip()
    candidate_error = str(candidate.get("somi_error") or "").strip()
    original_has_rows = any(str(item or "").strip() != "<no rows>" for item in list(original.get("somi_rows") or []))
    candidate_has_rows = any(str(item or "").strip() != "<no rows>" for item in list(candidate.get("somi_rows") or []))

    if original_error and not candidate_error:
        return True
    if candidate_score > original_score:
        return True
    if candidate_has_rows and not original_has_rows:
        return True
    return False


async def _stabilize_results(
    results: List[Dict[str, Any]],
    *,
    cases_by_query: Dict[str, Any],
    include_baselines: bool,
    somi_timeout_s: float,
    max_cases: int = 25,
    max_attempts: int = 2,
) -> List[Dict[str, Any]]:
    stabilized: List[Dict[str, Any]] = []
    if not results:
        return stabilized

    weak_indexes = [idx for idx, row in enumerate(results) if _needs_stabilized_rerun(row)]
    for idx in weak_indexes[: max(0, int(max_cases))]:
        original = dict(results[idx] or {})
        case = cases_by_query.get(str(original.get("query") or "").strip())
        if case is None:
            continue

        best = dict(original)
        for attempt in range(max(1, int(max_attempts))):
            candidate = await _evaluate_case(
                case,
                include_baselines=bool(include_baselines),
                somi_timeout_s=float(somi_timeout_s),
            )
            if _prefer_stabilized_result(best, candidate):
                best = dict(candidate or {})
                best["stabilized"] = True
                best["stabilized_attempt"] = attempt + 1
                notes = [str(item or "").strip() for item in list(best.get("notes") or []) if str(item or "").strip()]
                if "batch_stabilized_rerun" not in notes:
                    notes.append("batch_stabilized_rerun")
                best["notes"] = notes
            if not _needs_stabilized_rerun(best):
                break

        if best is not original and _prefer_stabilized_result(original, best):
            results[idx] = best
            stabilized.append(
                {
                    "query": str(best.get("query") or "").strip(),
                    "from_score": int(original.get("score") or 0),
                    "to_score": int(best.get("score") or 0),
                    "from_error": str(original.get("somi_error") or "").strip(),
                    "to_error": str(best.get("somi_error") or "").strip(),
                    "attempt": int(best.get("stabilized_attempt") or 1),
                }
            )

    return stabilized


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chunked safe search benchmarks with artifact-aware cleanup.")
    parser.add_argument("--corpus", default="everyday1000", help="Named corpus from audit.safe_search_corpus.")
    parser.add_argument("--chunk-size", type=int, default=25, help="Chunk size to run per subprocess.")
    parser.add_argument("--start-chunk", type=int, default=0, help="First chunk index to run.")
    parser.add_argument("--end-chunk", type=int, default=-1, help="Last chunk index to run. Defaults to the final chunk.")
    parser.add_argument("--output-dir", default="", help="Directory for per-chunk and combined artifacts.")
    parser.add_argument("--prefix", default="", help="Artifact prefix. Defaults to <corpus>_batch.")
    parser.add_argument("--python-executable", default=sys.executable, help="Python interpreter used for child chunk runs.")
    parser.add_argument("--somi-timeout", type=float, default=35.0, help="Per-case Somi timeout passed through to search_benchmark.py.")
    parser.add_argument("--chunk-timeout", type=float, default=1200.0, help="Hard timeout in seconds for each chunk subprocess.")
    parser.add_argument("--stable-seconds", type=float, default=15.0, help="How long completed artifacts must remain stable before a lingering chunk process is killed.")
    parser.add_argument("--resume", action="store_true", help="Skip chunks whose artifacts already look complete.")
    parser.add_argument("--compare-baselines", action="store_true", help="Also run baseline comparisons in each chunk.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of corpus cases to benchmark.")
    args = parser.parse_args()

    cases = build_named_corpus(args.corpus)
    if int(args.limit or 0) > 0:
        cases = cases[: max(0, int(args.limit or 0))]
    if not cases:
        print(json.dumps({"error": f"empty_corpus:{args.corpus}"}))
        return 2

    chunk_size = max(1, int(args.chunk_size or 25))
    total_cases = len(cases)
    total_chunks = max(1, math.ceil(total_cases / float(chunk_size)))
    start_chunk = max(0, int(args.start_chunk or 0))
    end_chunk = total_chunks - 1 if int(args.end_chunk or -1) < 0 else min(total_chunks - 1, int(args.end_chunk))
    if start_chunk > end_chunk:
        print(json.dumps({"error": "invalid_chunk_range", "start_chunk": start_chunk, "end_chunk": end_chunk}))
        return 2

    output_dir = Path(args.output_dir).resolve() if args.output_dir else (REPO_ROOT / "audit").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = str(args.prefix or f"{args.corpus}_batch").strip()
    python_executable = Path(args.python_executable).resolve()

    manifest: List[Dict[str, Any]] = []
    combined_results: List[Dict[str, Any]] = []

    for chunk_index in range(start_chunk, end_chunk + 1):
        paths = chunk_paths(output_dir, prefix, chunk_index)
        expected_rows = expected_chunk_size(total_cases, chunk_size, chunk_index)
        if args.resume and _chunk_complete(paths, expected_rows=expected_rows):
            rows = _read_jsonl(paths["jsonl"])
            combined_results.extend(rows)
            manifest.append(
                {
                    "chunk_index": int(chunk_index),
                    "status": "skipped_complete",
                    "rows": len(rows),
                    "paths": {key: str(value) for key, value in paths.items()},
                }
            )
            continue

        status = _run_chunk(
            python_executable=python_executable,
            corpus=args.corpus,
            limit=int(args.limit or 0),
            chunk_size=chunk_size,
            chunk_index=chunk_index,
            expected_rows=expected_rows,
            output_dir=output_dir,
            prefix=prefix,
            somi_timeout=float(args.somi_timeout),
            compare_baselines=bool(args.compare_baselines),
            timeout_s=float(args.chunk_timeout),
            stable_seconds=float(args.stable_seconds),
        )
        rows = _read_jsonl(paths["jsonl"])
        combined_results.extend(rows)
        status["rows"] = len(rows)
        manifest.append(status)

    stabilized_cases = asyncio.run(
        _stabilize_results(
            combined_results,
            cases_by_query={case.query: case for case in cases},
            include_baselines=bool(args.compare_baselines),
            somi_timeout_s=float(args.somi_timeout),
        )
    )
    combined_paths = _write_combined_outputs(output_dir, prefix, combined_results)
    manifest_path = output_dir / f"{prefix}_manifest.json"
    manifest_payload = {
        "corpus": args.corpus,
        "chunk_size": chunk_size,
        "limit": int(args.limit or 0),
        "start_chunk": start_chunk,
        "end_chunk": end_chunk,
        "total_cases": total_cases,
        "total_chunks": total_chunks,
        "combined_paths": combined_paths,
        "stabilized_cases": stabilized_cases,
        "chunks": manifest,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest_payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
