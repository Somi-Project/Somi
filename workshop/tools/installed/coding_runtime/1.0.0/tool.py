from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from workshop.toolbox.coding import (
    CodingJobStore,
    CodingSessionStore,
    build_project_context_memory,
    build_repo_map,
    create_workspace_rollback,
    get_repo_task_benchmark_pack,
    list_coding_backends,
    list_workspace_snapshots,
    load_workspace_manifest,
    prepare_repo_snapshot_sandbox,
    preview_static_workspace,
    resolve_workspace_root,
    restore_workspace_rollback,
    run_node_script,
    run_npm_script,
    run_npx_command,
    run_verify_loop,
    run_workspace_command,
    sandbox_status_report,
    workspace_health_report,
    workspace_backend_key,
    workspace_profile_key,
)


def _string_list(items: Any) -> list[str]:
    return [str(x) for x in list(items or []) if str(x).strip()]


def _persist_session_state(
    *,
    args: dict[str, Any],
    health: dict[str, Any] | None = None,
    benchmark_pack: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
    repo_map: dict[str, Any] | None = None,
    active_job: dict[str, Any] | None = None,
    coding_memory: dict[str, Any] | None = None,
) -> None:
    session_id = str(args.get("session_id") or "").strip()
    if not session_id:
        return
    store = CodingSessionStore()
    metadata_patch: dict[str, Any] = {}
    if isinstance(health, dict):
        metadata_patch["environment_health"] = health
    if isinstance(benchmark_pack, dict):
        metadata_patch["benchmark_pack"] = benchmark_pack
    if isinstance(scorecard, dict):
        metadata_patch["last_scorecard"] = scorecard
    if isinstance(repo_map, dict):
        metadata_patch["repo_map"] = repo_map
    if isinstance(active_job, dict):
        metadata_patch["active_job"] = active_job
    if isinstance(coding_memory, dict):
        metadata_patch["coding_memory"] = coding_memory
    if metadata_patch:
        store.update_session(session_id, metadata_patch=metadata_patch)


def _active_job_for_args(args: dict[str, Any], *, root_path: Path, profile_key: str) -> dict[str, Any]:
    session_id = str(args.get("session_id") or "").strip()
    if not session_id:
        session = CodingSessionStore().get_active_session(str(args.get("user_id") or "").strip())
        session_id = str(dict(session or {}).get("session_id") or "").strip()
    if not session_id:
        return {}
    objective = str(args.get("objective") or "").strip()
    repo_map = build_repo_map(root_path, objective=objective)
    return CodingJobStore().start_or_resume_job(
        session_id=session_id,
        objective=objective,
        workspace_root=str(root_path),
        profile_key=profile_key,
        repo_focus_files=list(repo_map.get("focus_files") or []),
    )


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()

    try:
        if action == "prepare_repo_snapshot":
            prepared = prepare_repo_snapshot_sandbox(
                str(args.get("source_root") or ""),
                user_id=str(args.get("user_id") or "default_user"),
                task_scope=str(args.get("task_scope") or ""),
                output_root=str(args.get("output_root") or ""),
            )
            return {"ok": True, **prepared}

        root_path = resolve_workspace_root(
            workspace_root=str(args.get("workspace_root") or ""),
            session_id=str(args.get("session_id") or ""),
            user_id=str(args.get("user_id") or ""),
        )
        timeout_s = int(args.get("timeout_s") or 45)
        output_cap = int(args.get("output_cap") or 20000)

        if action == "run_node_script":
            result = run_node_script(
                root_path,
                str(args.get("relative_path") or ""),
                script_args=_string_list(args.get("script_args") or []),
                timeout_s=timeout_s,
                output_cap=output_cap,
                backend_key=str(args.get("backend_key") or ""),
            )
            result["workspace_root"] = str(root_path)
            return result

        if action == "run_npm_script":
            result = run_npm_script(
                root_path,
                str(args.get("script_name") or ""),
                script_args=_string_list(args.get("script_args") or []),
                timeout_s=timeout_s,
                output_cap=output_cap,
                backend_key=str(args.get("backend_key") or ""),
            )
            result["workspace_root"] = str(root_path)
            return result

        if action == "run_npx":
            result = run_npx_command(
                root_path,
                _string_list(args.get("command_args") or []),
                timeout_s=timeout_s,
                output_cap=output_cap,
                backend_key=str(args.get("backend_key") or ""),
            )
            result["workspace_root"] = str(root_path)
            return result

        if action == "run_profile_check":
            manifest = load_workspace_manifest(root_path)
            profile_key = workspace_profile_key(root_path)
            health = workspace_health_report(root_path, refresh=True)
            benchmark_pack = get_repo_task_benchmark_pack(profile_key, health=health)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=profile_key)
            coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
            test_command = str(manifest.get("test_command") or "").strip()
            if profile_key in {"web", "game"}:
                preview = preview_static_workspace(root_path)
                result = {
                    "ok": bool(preview.get("exists")),
                    "workspace_root": str(root_path),
                    "profile_key": profile_key,
                    "check": "static_entrypoint",
                    "preview": preview,
                    "health": health,
                    "benchmark_pack": benchmark_pack,
                    "repo_map": repo_map,
                    "active_job": active_job,
                    "coding_memory": coding_memory,
                    "error": "" if bool(preview.get("exists")) else f"Static entrypoint missing: {preview.get('entrypoint')}",
                }
                if active_job.get("job_id"):
                    active_job = CodingJobStore().record_step(
                        job_id=str(active_job.get("job_id") or ""),
                        step_type="verify",
                        status="passed" if bool(preview.get("exists")) else "failed",
                        command=str(preview.get("entrypoint") or ""),
                        files=[str(preview.get("entrypoint") or "")] if str(preview.get("entrypoint") or "").strip() else [],
                        notes=result["error"] or "Static preview entrypoint is present.",
                    )
                    result["active_job"] = active_job
                _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
                return result
            if not test_command:
                result = {
                    "ok": False,
                    "workspace_root": str(root_path),
                    "profile_key": profile_key,
                    "health": health,
                    "benchmark_pack": benchmark_pack,
                    "repo_map": repo_map,
                    "active_job": active_job,
                    "coding_memory": coding_memory,
                    "error": "No test command defined for workspace profile",
                }
                if active_job.get("job_id"):
                    active_job = CodingJobStore().record_step(
                        job_id=str(active_job.get("job_id") or ""),
                        step_type="verify",
                        status="failed",
                        notes=result["error"],
                    )
                    result["active_job"] = active_job
                _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
                return result
            if bool(health.get("dependency_install_required")) and test_command.split()[0].lower() in {"npm", "npx", "pnpm", "bun"}:
                result = {
                    "ok": False,
                    "workspace_root": str(root_path),
                    "profile_key": profile_key,
                    "health": health,
                    "benchmark_pack": benchmark_pack,
                    "repo_map": repo_map,
                    "active_job": active_job,
                    "coding_memory": coding_memory,
                    "error": "Project dependencies are not installed yet",
                }
                if active_job.get("job_id"):
                    active_job = CodingJobStore().record_step(
                        job_id=str(active_job.get("job_id") or ""),
                        step_type="verify",
                        status="failed",
                        command=test_command,
                        notes=result["error"],
                    )
                    result["active_job"] = active_job
                _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
                return result
            result = run_workspace_command(
                root_path,
                test_command,
                timeout_s=timeout_s,
                output_cap=output_cap,
                backend_key=str(args.get("backend_key") or ""),
            )
            result["workspace_root"] = str(root_path)
            result["profile_key"] = profile_key
            result["health"] = health
            result["benchmark_pack"] = benchmark_pack
            result["repo_map"] = repo_map
            result["active_job"] = active_job
            result["coding_memory"] = coding_memory
            if active_job.get("job_id"):
                active_job = CodingJobStore().record_step(
                    job_id=str(active_job.get("job_id") or ""),
                    step_type="verify",
                    status="passed" if bool(result.get("ok")) else "failed",
                    command=test_command,
                    files=list(repo_map.get("focus_files") or [])[:4],
                    notes=str(result.get("stderr") or result.get("stdout") or "").strip()[:200],
                    score=100.0 if bool(result.get("ok")) else 35.0,
                )
                result["active_job"] = active_job
            _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
            return result

        if action == "workspace_health":
            health = workspace_health_report(root_path, refresh=True)
            benchmark_pack = get_repo_task_benchmark_pack(workspace_profile_key(root_path), health=health)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=workspace_profile_key(root_path))
            coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
            result = {
                "ok": bool(health.get("ok", False)),
                "workspace_root": str(root_path),
                "profile_key": workspace_profile_key(root_path),
                "health": health,
                "benchmark_pack": benchmark_pack,
                "repo_map": repo_map,
                "active_job": active_job,
                "coding_memory": coding_memory,
            }
            _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
            return result

        if action == "list_backends":
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "active_backend": workspace_backend_key(root_path),
                "backends": list_coding_backends(root_path),
            }

        if action == "sandbox_status":
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "sandbox": sandbox_status_report(root_path),
            }

        if action == "create_snapshot":
            snapshot = create_workspace_rollback(root_path, label=str(args.get("label") or "manual"))
            return {"ok": True, "workspace_root": str(root_path), "snapshot": snapshot}

        if action == "restore_snapshot":
            restored = restore_workspace_rollback(root_path, str(args.get("snapshot_id") or ""))
            return {"ok": True, "workspace_root": str(root_path), **restored}

        if action == "list_snapshots":
            return {
                "ok": True,
                "workspace_root": str(root_path),
                "snapshots": list_workspace_snapshots(root_path),
            }

        if action == "benchmark_pack":
            health = workspace_health_report(root_path, refresh=True)
            benchmark_pack = get_repo_task_benchmark_pack(workspace_profile_key(root_path), health=health)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=workspace_profile_key(root_path))
            coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
            result = {
                "ok": True,
                "workspace_root": str(root_path),
                "profile_key": workspace_profile_key(root_path),
                "health": health,
                "benchmark_pack": benchmark_pack,
                "repo_map": repo_map,
                "active_job": active_job,
                "coding_memory": coding_memory,
            }
            _persist_session_state(args=args, health=health, benchmark_pack=benchmark_pack, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
            return result

        if action == "repo_map":
            profile_key = workspace_profile_key(root_path)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=profile_key)
            return {"ok": True, "workspace_root": str(root_path), "profile_key": profile_key, "repo_map": repo_map, "active_job": active_job}

        if action == "start_job":
            profile_key = workspace_profile_key(root_path)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=profile_key)
            coding_memory = build_project_context_memory(repo_map=repo_map, health=workspace_health_report(root_path, refresh=False), active_job=active_job)
            _persist_session_state(args=args, repo_map=repo_map, active_job=active_job, coding_memory=coding_memory)
            return {"ok": True, "workspace_root": str(root_path), "profile_key": profile_key, "job": active_job, "repo_map": repo_map, "coding_memory": coding_memory}

        if action == "job_status":
            job_id = str(args.get("job_id") or "").strip()
            if job_id:
                job = CodingJobStore().load_job(job_id)
            else:
                session_id = str(args.get("session_id") or "").strip()
                job = CodingJobStore().get_active_job(session_id) if session_id else None
            return {"ok": True, "workspace_root": str(root_path), "job": job or {}}

        if action == "record_job_step":
            job_id = str(args.get("job_id") or "").strip()
            if not job_id:
                active_job = _active_job_for_args(args, root_path=root_path, profile_key=workspace_profile_key(root_path))
                job_id = str(active_job.get("job_id") or "")
            job = CodingJobStore().record_step(
                job_id=job_id,
                step_type=str(args.get("step_type") or "step"),
                status=str(args.get("status") or "completed"),
                command=str(args.get("command") or ""),
                files=_string_list(args.get("files") or []),
                notes=str(args.get("notes") or ""),
                score=float(args.get("score") or 0.0) if args.get("score") is not None else None,
            )
            _persist_session_state(args=args, active_job=job)
            return {"ok": True, "workspace_root": str(root_path), "job": job}

        if action == "complete_job":
            job_id = str(args.get("job_id") or "").strip()
            if not job_id:
                active_job = _active_job_for_args(args, root_path=root_path, profile_key=workspace_profile_key(root_path))
                job_id = str(active_job.get("job_id") or "")
            job = CodingJobStore().complete_job(job_id, status=str(args.get("status") or "completed"), notes=str(args.get("notes") or ""))
            _persist_session_state(args=args, active_job=job)
            return {"ok": True, "workspace_root": str(root_path), "job": job}

        if action == "run_verify_loop":
            result = run_verify_loop(root_path, timeout_s=timeout_s, output_cap=output_cap)
            repo_map = build_repo_map(root_path, objective=str(args.get("objective") or ""))
            active_job = _active_job_for_args(args, root_path=root_path, profile_key=str(result.get("profile_key") or workspace_profile_key(root_path)))
            if active_job.get("job_id"):
                command = ""
                for row in list(result.get("steps") or []):
                    if str(row.get("name") or "") == "test_command":
                        command = str(row.get("command") or "")
                        break
                active_job = CodingJobStore().record_step(
                    job_id=str(active_job.get("job_id") or ""),
                    step_type="verify",
                    status="passed" if bool(result.get("ok")) else "failed",
                    command=command,
                    files=list(repo_map.get("focus_files") or [])[:4],
                    notes=str(dict(result.get("scorecard") or {}).get("summary") or ""),
                    score=float(dict(result.get("scorecard") or {}).get("score") or 0.0),
                )
            coding_memory = build_project_context_memory(repo_map=repo_map, health=dict(result.get("health") or {}), active_job=active_job)
            result["repo_map"] = repo_map
            result["active_job"] = active_job
            result["coding_memory"] = coding_memory
            _persist_session_state(
                args=args,
                health=dict(result.get("health") or {}),
                benchmark_pack=dict(result.get("benchmark_pack") or {}),
                scorecard=dict(result.get("scorecard") or {}),
                repo_map=repo_map,
                active_job=active_job,
                coding_memory=coding_memory,
            )
            return result

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
