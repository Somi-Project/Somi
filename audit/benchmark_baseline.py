from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

from learning import build_scorecard
from speech.doctor import run_speech_doctor
from workshop.toolbox.registry import ToolRegistry

from .finality_lab import load_latest_finality_run
from .benchmark_packs import list_benchmark_packs
from .regression_packs import list_regression_packs


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _relative_exists(root_dir: Path, relative_path: str) -> bool:
    return (root_dir / str(relative_path or "").strip()).exists()


def _latest_finality_measurement(root_dir: Path, pack_id: str) -> dict[str, Any]:
    report = load_latest_finality_run(root_dir)
    if not isinstance(report, dict):
        return {}
    for row in list(report.get("packs") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip().lower() == str(pack_id or "").strip().lower():
            return dict(row)
    return {}


def _pack_observation(pack_id: str, *, root_dir: Path, registry: ToolRegistry, user_id: str) -> dict[str, Any]:
    if pack_id == "ocr":
        templates_path = root_dir / "config" / "ocr_templates.json"
        template_count = 0
        try:
            payload = json.loads(templates_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                template_count = len(payload)
            elif isinstance(payload, list):
                template_count = len(payload)
        except Exception:
            template_count = 0
        sample_images = len(list((root_dir / "sessions" / "ocr_tmp").glob("*.*"))) if (root_dir / "sessions" / "ocr_tmp").exists() else 0
        benchmark_summary: dict[str, Any] = {}
        try:
            from workshop.toolbox.stacks.ocr_core.benchmarks import run_document_benchmarks

            benchmark_summary = run_document_benchmarks(root_dir=root_dir / "sessions" / "ocr_benchmarks")
        except Exception:
            benchmark_summary = {}
        return {
            "template_count": template_count,
            "sample_image_count": sample_images,
            "structured_mode_available": bool(registry.find("ocr.extract")),
            "benchmark_average_parse_ms": float(benchmark_summary.get("average_parse_ms", 0.0) or 0.0),
            "benchmark_report_path": str(benchmark_summary.get("report_path") or ""),
            "finality_measured": bool(benchmark_summary.get("ok", False)),
        }

    if pack_id == "coding":
        try:
            from config.settings import CODING_DEFAULT_LANGUAGE, CODING_SUPPORTED_PROFILES, CODING_WORKSPACE_ROOT

            workspace_root = root_dir / str(CODING_WORKSPACE_ROOT)
            return {
                "default_language": str(CODING_DEFAULT_LANGUAGE),
                "supported_profiles": [str(x) for x in CODING_SUPPORTED_PROFILES],
                "workspace_root_exists": workspace_root.exists(),
                "finality_measured": False,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "finality_measured": False}

    if pack_id == "research":
        return {
            "regression_pack_count": len(list_regression_packs()),
            "chat_flow_harness_present": (root_dir / "audit" / "simulate_chat_flow_regression.py").exists(),
            "stress_harness_present": (root_dir / "runtime" / "live_chat_stress.py").exists(),
            "finality_measured": False,
        }

    if pack_id == "speech":
        try:
            report = run_speech_doctor()
            return {
                "doctor_ok": bool(report.get("ok", False)),
                "recommended_tts": str(dict(report.get("recommended") or {}).get("tts_provider") or ""),
                "recommended_stt": str(dict(report.get("recommended") or {}).get("stt_provider") or ""),
                "audio_available": bool(dict(report.get("audio") or {}).get("available", False)),
                "finality_measured": False,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "finality_measured": False}

    if pack_id == "automation":
        return {
            "gateway_manager_present": (root_dir / "gateway" / "manager.py").exists(),
            "heartbeat_service_present": (root_dir / "heartbeat" / "service.py").exists(),
            "automation_tests_present": (root_dir / "tests" / "test_delivery_automations_phase9.py").exists(),
            "finality_measured": False,
        }

    if pack_id == "browser":
        try:
            from workshop.toolbox.browser.runtime import browser_health

            health = browser_health()
            return {
                "browser_runtime_ok": bool(health.get("ok", False)),
                "executable_path": str(health.get("executable_path") or ""),
                "install_hint": str(health.get("install_hint") or ""),
                "finality_measured": False,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "finality_measured": False}

    if pack_id == "memory":
        try:
            scorecard = build_scorecard(user_id=user_id)
            return {
                "turn_count": _safe_int(scorecard.get("turn_count")),
                "factual_grounding_rate": float(scorecard.get("factual_grounding_rate", 0.0) or 0.0),
                "tool_success_rate": float(scorecard.get("tool_success_rate", 0.0) or 0.0),
                "finality_measured": False,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "finality_measured": False}

    return {"finality_measured": False}


def _evaluate_pack(pack: dict[str, Any], *, root_dir: Path, registry: ToolRegistry, user_id: str) -> dict[str, Any]:
    required_tools = [str(x) for x in list(pack.get("required_tools") or [])]
    required_modules = [str(x) for x in list(pack.get("required_modules") or [])]
    required_paths = [str(x) for x in list(pack.get("required_paths") or [])]
    benchmark_hooks = [str(x) for x in list(pack.get("benchmark_hooks") or [])]

    tool_hits = {name: bool(registry.find(name)) for name in required_tools}
    module_hits = {name: _module_available(name) for name in required_modules}
    path_hits = {name: _relative_exists(root_dir, name) for name in required_paths}
    hook_hits = {name: _relative_exists(root_dir, name) for name in benchmark_hooks}

    missing_tools = sorted([name for name, ok in tool_hits.items() if not ok])
    missing_modules = sorted([name for name, ok in module_hits.items() if not ok])
    missing_paths = sorted([name for name, ok in path_hits.items() if not ok])
    missing_hooks = sorted([name for name, ok in hook_hits.items() if not ok])

    observation = _pack_observation(str(pack.get("id") or ""), root_dir=root_dir, registry=registry, user_id=user_id)
    latest_measurement = _latest_finality_measurement(root_dir, str(pack.get("id") or ""))
    if latest_measurement:
        observation = {
            **observation,
            "finality_measured": bool(latest_measurement.get("finality_measured", latest_measurement.get("ok", False))),
            "latest_finality_run_id": str(latest_measurement.get("run_id") or ""),
            "latest_time_to_finality_ms": _safe_int(latest_measurement.get("time_to_finality_ms")),
            "latest_finality_metrics": dict(latest_measurement.get("metrics") or {}),
            "latest_task_pack": dict(latest_measurement.get("task_pack") or {}),
            "latest_finality_status": str(latest_measurement.get("status") or ""),
        }
    finality_measured = bool(observation.get("finality_measured", False))

    present = sum(1 for ok in [*tool_hits.values(), *module_hits.values(), *path_hits.values(), *hook_hits.values()] if ok)
    total = len(tool_hits) + len(module_hits) + len(path_hits) + len(hook_hits)
    readiness_score = round((present / max(1, total)) * 100.0, 2)

    core_missing = bool(missing_tools or missing_modules or missing_paths)
    benchmark_ready = not core_missing and not missing_hooks
    if core_missing:
        status = "gap"
    elif finality_measured:
        status = "measured"
    elif benchmark_ready:
        status = "ready"
    else:
        status = "partial"

    gaps: list[dict[str, Any]] = []
    if core_missing:
        gaps.append(
            {
                "gap_id": f"{pack['id']}.core_missing",
                "pack_id": pack["id"],
                "severity": "HIGH",
                "title": f"{pack['label']} core benchmark dependencies are incomplete",
                "detail": {
                    "missing_tools": missing_tools,
                    "missing_modules": missing_modules,
                    "missing_paths": missing_paths,
                },
                "recommended_fix": "Restore the missing runtime pieces before trusting this benchmark branch.",
            }
        )
    if not core_missing and missing_hooks:
        gaps.append(
            {
                "gap_id": f"{pack['id']}.benchmark_hooks_missing",
                "pack_id": pack["id"],
                "severity": "MEDIUM",
                "title": f"{pack['label']} lacks one or more benchmark hooks",
                "detail": {"missing_hooks": missing_hooks},
                "recommended_fix": "Add or restore the benchmark script or test entrypoints for this branch.",
            }
        )
    if benchmark_ready and not finality_measured:
        gaps.append(
            {
                "gap_id": f"{pack['id']}.finality_baseline_pending",
                "pack_id": pack["id"],
                "severity": "MEDIUM",
                "title": f"{pack['label']} finality baseline has not been captured yet",
                "detail": {"target_metrics": list(pack.get("target_metrics") or [])},
                "recommended_fix": "Run a branch-specific benchmark cycle and persist timing and quality measurements.",
            }
        )

    return {
        "id": pack["id"],
        "label": pack["label"],
        "objective": pack.get("objective"),
        "status": status,
        "readiness_score": readiness_score,
        "coverage": {
            "tools": tool_hits,
            "modules": module_hits,
            "paths": path_hits,
            "benchmark_hooks": hook_hits,
        },
        "missing": {
            "tools": missing_tools,
            "modules": missing_modules,
            "paths": missing_paths,
            "benchmark_hooks": missing_hooks,
        },
        "target_metrics": list(pack.get("target_metrics") or []),
        "polish_targets": list(pack.get("polish_targets") or []),
        "observations": observation,
        "gaps": gaps,
    }


def build_benchmark_baseline(root_dir: str | Path = ".", *, user_id: str = "default_user") -> dict[str, Any]:
    root = Path(root_dir)
    registry = ToolRegistry(path=str(root / "workshop" / "tools" / "registry.json"))
    packs = list_benchmark_packs()
    evaluations = [_evaluate_pack(pack, root_dir=root, registry=registry, user_id=user_id) for pack in packs]
    gap_ledger = [gap for item in evaluations for gap in list(item.get("gaps") or [])]

    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for item in evaluations:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    for gap in gap_ledger:
        severity = str(gap.get("severity") or "UNKNOWN")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    return {
        "generated_at": _now_iso(),
        "user_id": user_id,
        "packs": evaluations,
        "gap_ledger": gap_ledger,
        "summary": {
            "pack_count": len(evaluations),
            "gap_count": len(gap_ledger),
            "status_counts": status_counts,
            "severity_counts": severity_counts,
        },
    }


def _render_gap_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Benchmark Gap Ledger",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Summary",
        "",
        f"- Pack count: {dict(report.get('summary') or {}).get('pack_count', 0)}",
        f"- Gap count: {dict(report.get('summary') or {}).get('gap_count', 0)}",
        f"- Status counts: {dict(report.get('summary') or {}).get('status_counts', {})}",
        f"- Severity counts: {dict(report.get('summary') or {}).get('severity_counts', {})}",
        "",
        "## Packs",
        "",
    ]
    for pack in list(report.get("packs") or []):
        lines.append(f"### {pack.get('label')} ({pack.get('id')})")
        lines.append("")
        lines.append(f"- Status: {pack.get('status')}")
        lines.append(f"- Readiness score: {pack.get('readiness_score')}")
        lines.append(f"- Objective: {pack.get('objective')}")
        lines.append(f"- Target metrics: {list(pack.get('target_metrics') or [])}")
        lines.append(f"- Polish targets: {list(pack.get('polish_targets') or [])}")
        lines.append(f"- Observations: {dict(pack.get('observations') or {})}")
        pack_gaps = list(pack.get("gaps") or [])
        if pack_gaps:
            lines.append("- Open gaps:")
            for gap in pack_gaps:
                lines.append(f"  - [{gap.get('severity')}] {gap.get('title')}")
                lines.append(f"    Recommended fix: {gap.get('recommended_fix')}")
        else:
            lines.append("- Open gaps: []")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_benchmark_baseline(
    root_dir: str | Path = ".",
    *,
    out_dir: str | Path = "sessions/evals",
    user_id: str = "default_user",
) -> dict[str, Any]:
    report = build_benchmark_baseline(root_dir=root_dir, user_id=user_id)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "benchmark_baseline.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "gap_ledger.md").write_text(_render_gap_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    report = write_benchmark_baseline()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
