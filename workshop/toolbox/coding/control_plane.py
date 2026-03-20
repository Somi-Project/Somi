from __future__ import annotations

from pathlib import Path
from typing import Any

from workshop.toolbox.coding.benchmarks import get_repo_task_benchmark_pack
from workshop.toolbox.coding.change_plan import build_change_plan, score_edit_risk
from workshop.toolbox.coding.git_ops import (
    workspace_git_commit,
    workspace_git_diff,
    workspace_git_publish_status,
    workspace_git_push,
    workspace_git_status,
)
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.repo_map import build_project_context_memory, build_repo_map
from workshop.toolbox.coding.sandbox import list_workspace_snapshots, prepare_repo_snapshot_workspace
from workshop.toolbox.coding.scorecards import build_environment_health
from workshop.toolbox.coding.scratchpad import build_coding_compaction_summary, build_coding_scratchpad
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.tooling import (
    create_workspace_rollback,
    list_workspace_files,
    preview_workspace_write_operation,
    read_workspace_text_file,
    resolve_workspace_root,
    restore_workspace_rollback,
    run_verify_loop,
    sandbox_status_report,
    workspace_profile_key,
    write_workspace_text_file,
)


def _safe_rows(items: list[Any], *, limit: int) -> list[Any]:
    return list(items or [])[: max(0, int(limit or 0))]


class CodexControlPlane:
    def __init__(
        self,
        *,
        coding_service: CodingSessionService | None = None,
        store: CodingSessionStore | None = None,
        job_store: CodingJobStore | None = None,
    ) -> None:
        self.coding_service = coding_service or CodingSessionService()
        self.store = store or self.coding_service.store
        self.job_store = job_store or self.coding_service.job_store

    def open_session(
        self,
        *,
        user_id: str,
        objective: str = "",
        source: str = "control_plane",
        title: str = "",
        preferred_workspace: str = "",
        metadata: dict[str, Any] | None = None,
        resume_active: bool = True,
    ) -> dict[str, Any]:
        return self.coding_service.open_session(
            user_id=str(user_id or "default_user"),
            source=str(source or "control_plane"),
            objective=str(objective or ""),
            title=str(title or ""),
            preferred_workspace=str(preferred_workspace or ""),
            metadata=dict(metadata or {}),
            resume_active=bool(resume_active),
        )

    def _load_session(self, *, session_id: str = "", user_id: str = "", objective: str = "", source: str = "control_plane") -> dict[str, Any]:
        session = self.store.load_session(str(session_id or "").strip()) if str(session_id or "").strip() else None
        if not isinstance(session, dict) and str(user_id or "").strip():
            session = self.store.get_active_session(str(user_id or "").strip())
        if not isinstance(session, dict) and (str(objective or "").strip() or str(user_id or "").strip()):
            session = self.open_session(
                user_id=str(user_id or "default_user").strip() or "default_user",
                objective=str(objective or ""),
                source=source,
            )
        return dict(session or {})

    def _job_for_session(self, session: dict[str, Any], *, repo_map: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return {}
        workspace = dict(session.get("workspace") or {})
        return self.job_store.start_or_resume_job(
            session_id=session_id,
            objective=str(session.get("objective") or ""),
            workspace_root=str(workspace.get("root_path") or ""),
            profile_key=str(workspace.get("profile_key") or workspace.get("language") or "python"),
            repo_focus_files=list(repo_map.get("focus_files") or []),
        )

    def _refresh_session_metadata(
        self,
        session: dict[str, Any],
        *,
        health: dict[str, Any],
        benchmark_pack: dict[str, Any],
        repo_map: dict[str, Any],
        active_job: dict[str, Any],
        coding_memory: dict[str, Any],
        last_scorecard: dict[str, Any] | None = None,
        last_edit_risk: dict[str, Any] | None = None,
        last_change_plan: dict[str, Any] | None = None,
    ) -> None:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return
        metadata_patch: dict[str, Any] = {
            "environment_health": dict(health or {}),
            "benchmark_pack": dict(benchmark_pack or {}),
            "repo_map": dict(repo_map or {}),
            "active_job": dict(active_job or {}),
            "coding_memory": dict(coding_memory or {}),
        }
        if isinstance(last_scorecard, dict):
            metadata_patch["last_scorecard"] = dict(last_scorecard)
        if isinstance(last_edit_risk, dict):
            metadata_patch["last_edit_risk"] = dict(last_edit_risk)
        if isinstance(last_change_plan, dict):
            metadata_patch["last_change_plan"] = dict(last_change_plan)
        session_payload = dict(session or {})
        session_payload["metadata"] = {**dict(session_payload.get("metadata") or {}), **metadata_patch}
        scratchpad = build_coding_scratchpad(
            session_payload,
            repo_map=repo_map,
            health=health,
            active_job=active_job,
            coding_memory=coding_memory,
            last_scorecard=dict(last_scorecard or {}),
            prior=dict(dict(session.get("metadata") or {}).get("scratchpad") or {}),
        )
        metadata_patch["scratchpad"] = scratchpad
        metadata_patch["compaction_summary"] = build_coding_compaction_summary(session_payload, scratchpad)
        self.store.update_session(session_id, metadata_patch=metadata_patch)

    def build_control_snapshot(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        source: str = "control_snapshot",
        include_file_previews: bool = False,
        max_preview_chars: int = 2400,
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source=source)
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        health = build_environment_health(root_path, refresh=False)
        profile_key = workspace_profile_key(root_path)
        benchmark_pack = get_repo_task_benchmark_pack(profile_key, health=health)
        repo_map = build_repo_map(root_path, objective=str(objective or session.get("objective") or ""))
        active_job = self._job_for_session(session, repo_map=repo_map)
        coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
        git_status = workspace_git_status(root_path)
        snapshots = list_workspace_snapshots(root_path, limit=6)
        sandbox = sandbox_status_report(root_path)
        workspace = dict(session.get("workspace") or {})
        change_plan = build_change_plan(
            objective=str(objective or session.get("objective") or ""),
            repo_map=repo_map,
            verify_command=str(workspace.get("test_command") or ""),
            run_command=str(workspace.get("run_command") or ""),
        )
        workspace_files = list_workspace_files(root_path, limit=30, recursive=True)
        file_previews: list[dict[str, Any]] = []
        if include_file_previews:
            preview_paths = [str(item) for item in list(repo_map.get("focus_files") or []) if str(item).strip()]
            if not preview_paths:
                preview_paths = [str(row.get("path") or "") for row in workspace_files if str(row.get("kind") or "") == "file"]
            for relative_path in preview_paths[:3]:
                try:
                    file_previews.append(read_workspace_text_file(root_path, relative_path, max_chars=max_preview_chars))
                except Exception as exc:
                    file_previews.append({"path": relative_path, "error": f"{type(exc).__name__}: {exc}"})
        self._refresh_session_metadata(
            session,
            health=health,
            benchmark_pack=benchmark_pack,
            repo_map=repo_map,
            active_job=active_job,
            coding_memory=coding_memory,
            last_change_plan=change_plan,
        )
        session = dict(self.store.load_session(str(session.get("session_id") or "")) or session)
        return {
            "ok": True,
            "session": session,
            "workspace": dict(session.get("workspace") or {}),
            "health": health,
            "benchmark_pack": benchmark_pack,
            "repo_map": repo_map,
            "active_job": active_job,
            "coding_memory": coding_memory,
            "scratchpad": dict(dict(session.get("metadata") or {}).get("scratchpad") or {}),
            "compaction_summary": str(dict(session.get("metadata") or {}).get("compaction_summary") or ""),
            "change_plan": dict(dict(session.get("metadata") or {}).get("last_change_plan") or change_plan),
            "edit_risk": dict(dict(session.get("metadata") or {}).get("last_edit_risk") or {}),
            "git": git_status,
            "snapshots": snapshots,
            "sandbox": sandbox,
            "workspace_files": workspace_files,
            "file_previews": file_previews,
        }

    def inspect_workspace(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        relative_paths: list[str] | None = None,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        snapshot = self.build_control_snapshot(
            session_id=session_id,
            user_id=user_id,
            objective=objective,
            source="inspect_workspace",
            include_file_previews=False,
        )
        if not bool(snapshot.get("ok")):
            return snapshot
        session = dict(snapshot.get("session") or {})
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        chosen = [str(item).strip() for item in list(relative_paths or []) if str(item).strip()]
        if not chosen:
            chosen = [str(item) for item in list(dict(snapshot.get("repo_map") or {}).get("focus_files") or []) if str(item).strip()]
        if not chosen:
            chosen = [
                str(row.get("path") or "")
                for row in list(snapshot.get("workspace_files") or [])
                if str(row.get("kind") or "") == "file"
            ]
        previews: list[dict[str, Any]] = []
        for relative_path in chosen[:5]:
            try:
                previews.append(read_workspace_text_file(root_path, relative_path, max_chars=max_chars))
            except Exception as exc:
                previews.append({"path": relative_path, "error": f"{type(exc).__name__}: {exc}"})
        return {
            "ok": True,
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(root_path),
            "files": previews,
            "repo_map": dict(snapshot.get("repo_map") or {}),
            "git": dict(snapshot.get("git") or {}),
        }

    def plan_change(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        relative_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        snapshot = self.build_control_snapshot(
            session_id=session_id,
            user_id=user_id,
            objective=objective,
            source="plan_change",
            include_file_previews=False,
        )
        if not bool(snapshot.get("ok")):
            return snapshot
        session = dict(snapshot.get("session") or {})
        workspace = dict(snapshot.get("workspace") or {})
        change_plan = build_change_plan(
            objective=str(objective or session.get("objective") or ""),
            repo_map=dict(snapshot.get("repo_map") or {}),
            relative_paths=relative_paths,
            verify_command=str(workspace.get("test_command") or ""),
            run_command=str(workspace.get("run_command") or ""),
        )
        return {
            "ok": True,
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(dict(snapshot.get("workspace") or {}).get("root_path") or ""),
            "change_plan": change_plan,
            "repo_map": dict(snapshot.get("repo_map") or {}),
        }

    def apply_text_edit(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        relative_path: str,
        content: str,
        mode: str = "overwrite",
        create_snapshot: bool = True,
        allow_large_write: bool = False,
        create_parents: bool = True,
        notes: str = "",
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="apply_text_edit")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        preview = preview_workspace_write_operation(root_path, relative_path, content, mode=mode)
        write_result = write_workspace_text_file(
            root_path,
            relative_path,
            content,
            mode=mode,
            create_parents=create_parents,
            create_snapshot=create_snapshot,
            allow_large_write=allow_large_write,
            snapshot_label=f"control_edit_{Path(str(relative_path)).stem or 'file'}",
        )
        repo_map = build_repo_map(root_path, objective=str(session.get("objective") or objective or ""))
        edit_risk = score_edit_risk(relative_path=relative_path, preview=preview, repo_map=repo_map, mode=mode)
        change_plan = build_change_plan(
            objective=str(session.get("objective") or objective or ""),
            repo_map=repo_map,
            relative_paths=[relative_path],
            verify_command=str(dict(session.get("workspace") or {}).get("test_command") or ""),
            run_command=str(dict(session.get("workspace") or {}).get("run_command") or ""),
        )
        health = build_environment_health(root_path, refresh=False)
        benchmark_pack = get_repo_task_benchmark_pack(workspace_profile_key(root_path), health=health)
        active_job = self._job_for_session(session, repo_map=repo_map)
        if active_job.get("job_id"):
            active_job = self.job_store.record_step(
                job_id=str(active_job.get("job_id") or ""),
                step_type="patch",
                status="completed",
                files=[str(relative_path)],
                notes=str(notes or preview.get("incoming_excerpt") or "Applied bounded text edit."),
                score=max(55.0, 92.0 - float(edit_risk.get("risk_score") or 0) * 0.3),
            )
        coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
        self._refresh_session_metadata(
            session,
            health=health,
            benchmark_pack=benchmark_pack,
            repo_map=repo_map,
            active_job=active_job,
            coding_memory=coding_memory,
            last_edit_risk=edit_risk,
            last_change_plan=change_plan,
        )
        return {
            "ok": True,
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(root_path),
            "preview": preview,
            "write": write_result,
            "edit_risk": edit_risk,
            "change_plan": change_plan,
            "git": workspace_git_status(root_path),
            "snapshots": list_workspace_snapshots(root_path, limit=6),
            "active_job": active_job,
        }

    def run_verify_cycle(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        timeout_s: int = 45,
        output_cap: int = 20000,
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="verify_cycle")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        result = run_verify_loop(root_path, timeout_s=timeout_s, output_cap=output_cap)
        repo_map = build_repo_map(root_path, objective=str(session.get("objective") or objective or ""))
        active_job = self._job_for_session(session, repo_map=repo_map)
        if active_job.get("job_id"):
            active_job = self.job_store.record_step(
                job_id=str(active_job.get("job_id") or ""),
                step_type="verify",
                status="passed" if bool(result.get("ok")) else "failed",
                command=str(dict(session.get("workspace") or {}).get("test_command") or ""),
                files=_safe_rows(list(repo_map.get("focus_files") or []), limit=4),
                notes=str(dict(result.get("scorecard") or {}).get("summary") or ""),
                score=float(dict(result.get("scorecard") or {}).get("finality_score") or 0.0),
            )
        coding_memory = build_project_context_memory(repo_map=repo_map, health=dict(result.get("health") or {}), active_job=active_job)
        self._refresh_session_metadata(
            session,
            health=dict(result.get("health") or {}),
            benchmark_pack=dict(result.get("benchmark_pack") or {}),
            repo_map=repo_map,
            active_job=active_job,
            coding_memory=coding_memory,
            last_scorecard=dict(result.get("scorecard") or {}),
        )
        return {
            **dict(result or {}),
            "session_id": str(session.get("session_id") or ""),
            "active_job": active_job,
            "git": workspace_git_status(root_path),
        }

    def create_snapshot(self, *, session_id: str = "", user_id: str = "", objective: str = "", label: str = "manual") -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="create_snapshot")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        snapshot = create_workspace_rollback(root_path, label=label)
        return {"ok": True, "session_id": str(session.get("session_id") or ""), "workspace_root": str(root_path), "snapshot": snapshot}

    def restore_snapshot(self, *, session_id: str = "", user_id: str = "", objective: str = "", snapshot_id: str) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="restore_snapshot")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        restored = restore_workspace_rollback(root_path, snapshot_id)
        return {"ok": True, "session_id": str(session.get("session_id") or ""), "workspace_root": str(root_path), **restored}

    def git_status(self, *, session_id: str = "", user_id: str = "", objective: str = "") -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="git_status")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        return {"ok": True, "session_id": str(session.get("session_id") or ""), "workspace_root": str(root_path), "git": workspace_git_status(root_path)}

    def git_diff(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        relative_path: str = "",
        staged: bool = False,
        max_chars: int = 16000,
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="git_diff")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        diff = workspace_git_diff(root_path, relative_path=relative_path, staged=staged, max_chars=max_chars)
        return {"ok": bool(diff.get("ok")), "session_id": str(session.get("session_id") or ""), "workspace_root": str(root_path), **diff}

    def git_commit(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        message: str,
        add_paths: list[str] | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="git_commit")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        commit = workspace_git_commit(root_path, message=message, add_paths=add_paths, allow_empty=allow_empty)
        repo_map = build_repo_map(root_path, objective=str(session.get("objective") or objective or ""))
        active_job = self._job_for_session(session, repo_map=repo_map)
        if active_job.get("job_id"):
            active_job = self.job_store.record_step(
                job_id=str(active_job.get("job_id") or ""),
                step_type="commit",
                status="passed" if bool(commit.get("ok")) else "failed",
                command=f"git commit -m {message}",
                files=[str(item) for item in list(add_paths or []) if str(item).strip()],
                notes=str(commit.get("last_commit") or commit.get("error") or ""),
                score=90.0 if bool(commit.get("ok")) else 30.0,
            )
        health = build_environment_health(root_path, refresh=False)
        benchmark_pack = get_repo_task_benchmark_pack(workspace_profile_key(root_path), health=health)
        coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
        self._refresh_session_metadata(
            session,
            health=health,
            benchmark_pack=benchmark_pack,
            repo_map=repo_map,
            active_job=active_job,
            coding_memory=coding_memory,
        )
        return {
            **dict(commit or {}),
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(root_path),
            "active_job": active_job,
            "publish_requires_confirmation": False,
        }

    def git_push(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        objective: str = "",
        remote: str = "origin",
        branch: str = "",
        set_upstream: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="git_push")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        push = workspace_git_push(root_path, remote=remote, branch=branch, set_upstream=set_upstream, dry_run=dry_run)
        repo_map = build_repo_map(root_path, objective=str(session.get("objective") or objective or ""))
        active_job = self._job_for_session(session, repo_map=repo_map)
        if active_job.get("job_id"):
            active_job = self.job_store.record_step(
                job_id=str(active_job.get("job_id") or ""),
                step_type="publish",
                status="passed" if bool(push.get("ok")) else "failed",
                command=f"git push {'--dry-run ' if dry_run else ''}{remote} {branch or str(dict(push.get('publish_status') or {}).get('branch') or '')}".strip(),
                notes=str(push.get("status") or push.get("error") or ""),
                score=92.0 if bool(push.get("ok")) else 25.0,
            )
        health = build_environment_health(root_path, refresh=False)
        benchmark_pack = get_repo_task_benchmark_pack(workspace_profile_key(root_path), health=health)
        coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
        self._refresh_session_metadata(
            session,
            health=health,
            benchmark_pack=benchmark_pack,
            repo_map=repo_map,
            active_job=active_job,
            coding_memory=coding_memory,
        )
        return {
            **dict(push or {}),
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(root_path),
            "active_job": active_job,
            "publish_requires_confirmation": True,
            "external_effect": True,
        }

    def publish_status(self, *, session_id: str = "", user_id: str = "", objective: str = "", remote: str = "origin", branch: str = "") -> dict[str, Any]:
        session = self._load_session(session_id=session_id, user_id=user_id, objective=objective, source="publish_status")
        if not session:
            return {"ok": False, "error": "No coding session is available."}
        root_path = resolve_workspace_root(session_id=str(session.get("session_id") or ""), store=self.store)
        return {
            "ok": True,
            "session_id": str(session.get("session_id") or ""),
            "workspace_root": str(root_path),
            "publish_status": workspace_git_publish_status(root_path, remote=remote, branch=branch),
        }

    def import_repo_snapshot(
        self,
        *,
        source_root: str,
        user_id: str = "default_user",
        objective: str = "",
        task_scope: str = "",
    ) -> dict[str, Any]:
        prepared = prepare_repo_snapshot_workspace(
            source_root,
            user_id=str(user_id or "default_user"),
            task_scope=str(task_scope or objective or ""),
        )
        root_path = Path(str(prepared.get("workspace_root") or "")).resolve()
        health = build_environment_health(root_path, refresh=True)
        profile_key = workspace_profile_key(root_path)
        repo_map = build_repo_map(root_path, objective=str(objective or ""))
        git_status = workspace_git_status(root_path)
        workspace_files = list_workspace_files(root_path, limit=20, recursive=True)
        return {
            **dict(prepared or {}),
            "health": health,
            "profile_key": profile_key,
            "repo_map": repo_map,
            "git": git_status,
            "workspace_files": workspace_files,
        }
