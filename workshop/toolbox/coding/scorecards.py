from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workshop.toolbox.coding.benchmarks import get_repo_task_benchmark_pack
from workshop.toolbox.coding.profiles import get_language_profile
from workshop.toolbox.coding.runtime_inventory import build_runtime_inventory
from workshop.toolbox.coding.sandbox import sandbox_status


_WORKSPACE_MANIFEST = ".somi_coding_workspace.json"


def _load_manifest(root_path: Path) -> dict[str, Any]:
    manifest_path = root_path / _WORKSPACE_MANIFEST
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _profile_key(manifest: dict[str, Any]) -> str:
    return str(manifest.get("profile_key") or manifest.get("language") or "python").strip().lower() or "python"


def _marker_labels(inventory: dict[str, Any]) -> set[str]:
    return {
        str(dict(row).get("label") or "").strip()
        for row in list(inventory.get("workspace_markers") or [])
        if str(dict(row).get("label") or "").strip()
    }


def _command_prefix(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    return text.split()[0].strip().lower()


def build_environment_health(root_path: Path, *, refresh: bool = False) -> dict[str, Any]:
    manifest = _load_manifest(root_path)
    profile_key = _profile_key(manifest)
    profile = get_language_profile(profile_key)
    inventory = build_runtime_inventory(workspace_root=str(root_path), refresh=refresh)
    available_keys = {
        str(item).strip().lower()
        for item in list(inventory.get("available_keys") or [])
        if str(item).strip()
    }
    markers = _marker_labels(inventory)

    entrypoint = str(manifest.get("entrypoint") or profile.entrypoint or "").strip()
    entrypoint_exists = bool(entrypoint) and (root_path / entrypoint).exists()
    run_command = str(manifest.get("run_command") or "").strip()
    test_command = str(manifest.get("test_command") or "").strip()

    package_json = root_path / "package.json"
    package_payload: dict[str, Any] = {}
    if package_json.exists():
        try:
            package_payload = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            package_payload = {}

    dependency_count = len(dict(package_payload.get("dependencies") or {})) + len(dict(package_payload.get("devDependencies") or {}))
    install_required = bool(package_json.exists() and dependency_count and not (root_path / "node_modules").exists())

    checks: list[dict[str, Any]] = []
    for idx, group in enumerate(profile.runtime_requirement_groups, start=1):
        normalized_group = [str(item).strip().lower() for item in group if str(item).strip()]
        matched = [key for key in normalized_group if key in available_keys]
        checks.append(
            {
                "name": f"runtime_group_{idx}",
                "label": "Runtime requirement",
                "detail": " / ".join(normalized_group) or "runtime",
                "ok": bool(matched),
                "severity": "error",
                "matched": matched,
            }
        )

    for marker in profile.required_markers:
        checks.append(
            {
                "name": f"marker_{marker}",
                "label": "Workspace marker",
                "detail": str(marker),
                "ok": str(marker) in markers,
                "severity": "warning",
                "matched": [str(marker)] if str(marker) in markers else [],
            }
        )

    checks.append(
        {
            "name": "entrypoint_exists",
            "label": "Entrypoint present",
            "detail": entrypoint or "(missing entrypoint)",
            "ok": entrypoint_exists,
            "severity": "error",
            "matched": [entrypoint] if entrypoint_exists else [],
        }
    )

    if run_command:
        checks.append(
            {
                "name": "run_command",
                "label": "Run command configured",
                "detail": run_command,
                "ok": True,
                "severity": "warning",
                "matched": [_command_prefix(run_command)] if _command_prefix(run_command) else [],
            }
        )
    if test_command:
        checks.append(
            {
                "name": "test_command",
                "label": "Test command configured",
                "detail": test_command,
                "ok": True,
                "severity": "warning",
                "matched": [_command_prefix(test_command)] if _command_prefix(test_command) else [],
            }
        )

    if package_json.exists():
        checks.append(
            {
                "name": "dependency_install_state",
                "label": "Node dependency state",
                "detail": "install required" if install_required else "ready or not required",
                "ok": not install_required,
                "severity": "warning",
                "matched": [] if install_required else ["node_modules"],
            }
        )

    error_checks = [row for row in checks if str(row.get("severity") or "") == "error"]
    warning_checks = [row for row in checks if str(row.get("severity") or "") == "warning"]
    error_failures = [row for row in error_checks if not bool(row.get("ok"))]
    warning_failures = [row for row in warning_checks if not bool(row.get("ok"))]

    score_weights = {"error": 20.0, "warning": 8.0}
    possible = sum(score_weights.get(str(row.get("severity") or ""), 0.0) for row in checks) or 1.0
    earned = sum(score_weights.get(str(row.get("severity") or ""), 0.0) for row in checks if bool(row.get("ok")))
    score = round((earned / possible) * 100.0, 2)

    status = "blocked" if error_failures else ("warning" if warning_failures else "healthy")
    recommendations: list[str] = []
    for row in error_failures:
        if row["name"].startswith("runtime_group_"):
            recommendations.append(f"Install or expose one of these runtimes: {row['detail']}.")
        elif row["name"] == "entrypoint_exists":
            recommendations.append(f"Create or restore the configured entrypoint: {row['detail']}.")
    for row in warning_failures:
        if row["name"].startswith("marker_"):
            recommendations.append(f"Restore the expected workspace marker: {row['detail']}.")
        elif row["name"] == "dependency_install_state":
            recommendations.append("Install project dependencies inside the workspace before running Node or TypeScript checks.")
    if not test_command and profile.key not in {"web", "game"}:
        recommendations.append("Add a light verification command so coding mode can close the loop automatically.")

    benchmark_pack = get_repo_task_benchmark_pack(profile.key, health={"ok": not error_failures, "status": status, "score": score})
    sandbox = sandbox_status(root_path)
    summary_bits = [
        f"{profile.display_name} workspace",
        f"status={status}",
        f"score={score}",
    ]
    summary_bits.append(f"sandbox={sandbox.get('active_backend')}")
    if recommendations:
        summary_bits.append(f"next={recommendations[0]}")

    return {
        "ok": not error_failures,
        "status": status,
        "score": score,
        "summary": " | ".join(summary_bits),
        "profile_key": profile.key,
        "profile_display_name": profile.display_name,
        "entrypoint": entrypoint,
        "entrypoint_exists": entrypoint_exists,
        "run_command": run_command,
        "test_command": test_command,
        "available_runtime_keys": sorted(available_keys),
        "checks": checks,
        "recommendations": recommendations,
        "markers_present": sorted(markers),
        "dependency_install_required": install_required,
        "sandbox": sandbox,
        "benchmark_pack": benchmark_pack,
    }


def build_coding_run_scorecard(
    *,
    root_path: Path,
    health: dict[str, Any],
    steps: list[dict[str, Any]],
    benchmark_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_steps = [row for row in steps if bool(row.get("required", True))]
    executed_steps = [row for row in steps if str(row.get("status") or "") == "executed"]
    failed_steps = [row for row in required_steps if not bool(row.get("ok"))]
    passed_steps = [row for row in required_steps if bool(row.get("ok"))]
    elapsed_ms = sum(int(row.get("elapsed_ms") or 0) for row in executed_steps)

    health_score = float(health.get("score", 0.0) or 0.0)
    step_score = (len(passed_steps) / max(1, len(required_steps))) * 100.0
    score = round((health_score * 0.4) + (step_score * 0.6), 2)

    if str(health.get("status") or "") == "blocked" or failed_steps:
        status = "red"
    elif str(health.get("status") or "") == "warning":
        status = "yellow"
    else:
        status = "green"

    next_actions = [str(item) for item in list(health.get("recommendations") or []) if str(item).strip()]
    for row in failed_steps:
        label = str(row.get("label") or row.get("name") or "verify step")
        error = str(row.get("error") or row.get("stderr") or "").strip()
        next_actions.append(f"Repair {label.lower()}" + (f": {error}" if error else "."))
    next_actions = list(dict.fromkeys(next_actions))

    pack = dict(benchmark_pack or health.get("benchmark_pack") or {})
    return {
        "workspace_root": str(root_path),
        "status": status,
        "score": score,
        "health_score": health_score,
        "verify_loop_success_rate": round(len(passed_steps) / max(1, len(required_steps)), 4),
        "executed_step_count": len(executed_steps),
        "successful_step_count": len(passed_steps),
        "failed_step_count": len(failed_steps),
        "time_to_finality_ms": elapsed_ms,
        "finality_measured": bool(required_steps) and not failed_steps,
        "summary": f"verify={status} | score={score} | steps={len(passed_steps)}/{max(1, len(required_steps))}",
        "next_actions": next_actions[:5],
        "benchmark_pack": pack,
    }
