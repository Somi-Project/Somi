from __future__ import annotations

from copy import deepcopy
from typing import Any


_PACK = {
    "id": "core_repo_tasks",
    "label": "Core Repo Tasks",
    "objective": "Measure how quickly a managed coding workspace can get from plan to verified output.",
    "consumer_hardware_profile": {
        "target_ram_gb": 8,
        "gpu_required": False,
        "network_required": False,
    },
    "profiles": {
        "python": {
            "tasks": [
                {
                    "id": "inspect_patch_python",
                    "label": "Inspect and patch Python source",
                    "success_signal": "main.py updated or new module added without leaving the managed workspace",
                },
                {
                    "id": "run_python_entrypoint",
                    "label": "Run the Python entrypoint",
                    "success_signal": "run_command exits cleanly",
                },
                {
                    "id": "green_pytest",
                    "label": "Get pytest green",
                    "success_signal": "test_command exits cleanly",
                },
            ],
            "target_metrics": [
                "time_to_first_patch_ms",
                "time_to_green_tests_ms",
                "workspace_health_score",
                "verify_loop_success_rate",
            ],
        },
        "javascript": {
            "tasks": [
                {
                    "id": "inspect_patch_js",
                    "label": "Inspect and patch JavaScript files",
                    "success_signal": "index.js or test files updated inside the managed workspace",
                },
                {
                    "id": "run_node_entrypoint",
                    "label": "Run the Node entrypoint",
                    "success_signal": "node execution exits cleanly",
                },
                {
                    "id": "run_js_tests",
                    "label": "Run the JavaScript test loop",
                    "success_signal": "npm test exits cleanly",
                },
            ],
            "target_metrics": [
                "time_to_first_patch_ms",
                "time_to_green_tests_ms",
                "workspace_health_score",
                "verify_loop_success_rate",
            ],
        },
        "typescript": {
            "tasks": [
                {
                    "id": "inspect_patch_ts",
                    "label": "Inspect and patch TypeScript source",
                    "success_signal": "src/index.ts or sibling files updated inside the managed workspace",
                },
                {
                    "id": "typecheck",
                    "label": "Run a bounded typecheck",
                    "success_signal": "TypeScript compile check exits cleanly",
                },
                {
                    "id": "verify_build_readiness",
                    "label": "Confirm build readiness",
                    "success_signal": "workspace health reports the toolchain as ready or clearly names the missing dependency",
                },
            ],
            "target_metrics": [
                "time_to_first_patch_ms",
                "typecheck_success_rate",
                "workspace_health_score",
                "dependency_readiness",
            ],
        },
        "web": {
            "tasks": [
                {
                    "id": "inspect_patch_ui",
                    "label": "Inspect and patch the static UI",
                    "success_signal": "index.html, styles.css, or app.js updated in place",
                },
                {
                    "id": "verify_entrypoint",
                    "label": "Verify the static entrypoint",
                    "success_signal": "preview entrypoint exists",
                },
                {
                    "id": "capture_ready_state",
                    "label": "Prepare for browser preview",
                    "success_signal": "workspace health reports the web surface as ready",
                },
            ],
            "target_metrics": [
                "time_to_first_patch_ms",
                "time_to_preview_ready_ms",
                "workspace_health_score",
                "verify_loop_success_rate",
            ],
        },
        "game": {
            "tasks": [
                {
                    "id": "inspect_patch_game",
                    "label": "Inspect and patch browser game files",
                    "success_signal": "game.js or canvas assets updated inside the managed workspace",
                },
                {
                    "id": "verify_canvas_entrypoint",
                    "label": "Verify the browser-game entrypoint",
                    "success_signal": "preview entrypoint exists",
                },
                {
                    "id": "prepare_preview",
                    "label": "Prepare for local preview",
                    "success_signal": "workspace health reports the game surface as ready",
                },
            ],
            "target_metrics": [
                "time_to_first_patch_ms",
                "time_to_preview_ready_ms",
                "workspace_health_score",
                "verify_loop_success_rate",
            ],
        },
    },
}


def list_repo_task_benchmarks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile_key in sorted(_PACK["profiles"]):
        rows.append(get_repo_task_benchmark_pack(profile_key))
    return rows


def get_repo_task_benchmark_pack(profile_key: str, *, health: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = str(profile_key or "python").strip().lower() or "python"
    profile_payload = dict(_PACK["profiles"].get(normalized) or _PACK["profiles"]["python"])
    pack = deepcopy(
        {
            "id": _PACK["id"],
            "label": _PACK["label"],
            "objective": _PACK["objective"],
            "profile_key": normalized,
            "consumer_hardware_profile": dict(_PACK["consumer_hardware_profile"]),
            "tasks": list(profile_payload.get("tasks") or []),
            "target_metrics": list(profile_payload.get("target_metrics") or []),
        }
    )
    health_payload = dict(health or {})
    score = float(health_payload.get("score", 0.0) or 0.0)
    pack["workspace_fit"] = {
        "health_score": score,
        "status": str(health_payload.get("status") or "unknown"),
        "recommended_first_task": str((pack["tasks"] or [{}])[0].get("label") or "").strip(),
        "ready_for_verify_loop": bool(health_payload.get("ok", False)),
    }
    return pack
