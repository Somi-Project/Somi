from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import (
    CODING_AGENT_PROFILE,
    CODING_DEFAULT_LANGUAGE,
    CODING_MODEL,
    CODING_SESSIONS_ROOT,
    CODING_SUPPORTED_PROFILES,
    CODING_WORKSPACE_ROOT,
)
from workshop.toolbox.coding.benchmarks import get_repo_task_benchmark_pack
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.models import CodingSessionSnapshot, CodingWorkspaceSnapshot
from workshop.toolbox.coding.profiles import get_language_profile, infer_language_profile, list_language_profiles
from workshop.toolbox.coding.repo_map import build_project_context_memory, build_repo_map
from workshop.toolbox.coding.scorecards import build_environment_health
from workshop.toolbox.coding.scratchpad import build_coding_compaction_summary, build_coding_scratchpad
from workshop.toolbox.coding.skill_drafts import build_skill_gap_prompt, detect_skill_gap
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager
from workshop.skills.forge import SkillForgeService


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_id(user_id: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(user_id or "default_user").strip().lower())[:40] or "default_user"
    return f"coding_{stem}_{uuid.uuid4().hex[:10]}"


def _clean_objective(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:1200]


class CodingSessionService:
    def __init__(
        self,
        *,
        store: CodingSessionStore | None = None,
        workspace_manager: CodingWorkspaceManager | None = None,
        job_store: CodingJobStore | None = None,
        skill_forge: SkillForgeService | None = None,
        coding_model: str | None = None,
        agent_profile: str | None = None,
    ) -> None:
        self.store = store or CodingSessionStore(root_dir=CODING_SESSIONS_ROOT)
        self.workspace_manager = workspace_manager or CodingWorkspaceManager(root_dir=CODING_WORKSPACE_ROOT)
        self.job_store = job_store or CodingJobStore()
        self.skill_forge = skill_forge or SkillForgeService()
        self.coding_model = str(coding_model or CODING_MODEL or "").strip()
        self.agent_profile = str(agent_profile or CODING_AGENT_PROFILE or "coding_worker").strip()

    def _build_compaction_state(
        self,
        session_payload: dict[str, Any],
        *,
        repo_map: dict[str, Any],
        health: dict[str, Any],
        active_job: dict[str, Any],
        coding_memory: dict[str, Any],
        last_scorecard: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        metadata = dict(session_payload.get("metadata") or {})
        scratchpad = build_coding_scratchpad(
            session_payload,
            repo_map=repo_map,
            health=health,
            active_job=active_job,
            coding_memory=coding_memory,
            last_scorecard=dict(last_scorecard or metadata.get("last_scorecard") or {}),
            prior=dict(metadata.get("scratchpad") or {}),
        )
        summary = build_coding_compaction_summary(session_payload, scratchpad)
        return scratchpad, summary

    def detect_trigger(self, prompt: str) -> dict[str, Any]:
        raw = str(prompt or "").strip()
        lowered = raw.lower()
        if not raw:
            return {"requested": False, "objective": "", "command": ""}

        direct_prefix = re.match(r"^(?:/code|/coding)\s*(.*)$", raw, flags=re.IGNORECASE)
        if direct_prefix:
            return {
                "requested": True,
                "command": "/code",
                "objective": _clean_objective(direct_prefix.group(1) or ""),
                "force_open": True,
            }

        if re.search(r"\b(coding mode|open coding workspace|switch to coding mode|enter coding mode)\b", lowered):
            return {
                "requested": True,
                "command": "coding_mode",
                "objective": _clean_objective(raw),
                "force_open": True,
            }

        if re.search(r"\b(write|build|create|fix|debug|refactor|implement|patch|review)\b", lowered) and re.search(
            r"\b(code|python|script|function|class|module|file|project|repo|repository|bug|traceback|test)\b",
            lowered,
        ):
            return {
                "requested": True,
                "command": "coding_intent",
                "objective": _clean_objective(raw),
                "force_open": False,
            }

        return {"requested": False, "objective": "", "command": ""}

    def build_welcome_text(self, snapshot: dict[str, Any]) -> str:
        workspace = dict(snapshot.get("workspace") or {})
        title = str(snapshot.get("title") or "Coding Session")
        objective = str(snapshot.get("objective") or "").strip()
        language = str(workspace.get("language") or "python")
        profile_display_name = str(workspace.get("profile_display_name") or language.title())
        runtime_profile = str(workspace.get("runtime_profile") or language)
        sandbox_backend = str(workspace.get("sandbox_backend") or dict(workspace.get("metadata") or {}).get("sandbox_backend") or "")
        task_scope = str(dict(workspace.get("metadata") or {}).get("task_scope") or "")
        available_runtime_keys: list[str] = []
        for row in list(workspace.get("available_runtimes") or []):
            if not bool(row.get("available")):
                continue
            label = str(row.get("key") or "")
            version = str(row.get("version") or "").strip()
            available_runtime_keys.append(f"{label} ({version})" if version else label)
        lines = [
            "Hi, welcome to coding mode.",
            f"Session: {title}",
            f"Workspace: {workspace.get('root_path') or '--'}",
            f"Agent: {snapshot.get('agent_profile') or self.agent_profile}",
            f"Model: {snapshot.get('coding_model') or self.coding_model or '--'}",
            f"Language: {language}",
            f"Profile: {profile_display_name}",
            f"Runtime Profile: {runtime_profile}",
        ]
        if sandbox_backend:
            lines.append(f"Sandbox: {sandbox_backend}")
        if task_scope:
            lines.append(f"Task Scope: {task_scope}")
        if objective:
            lines.append(f"Objective: {objective}")
        if available_runtime_keys:
            lines.append(f"Available runtimes: {', '.join(available_runtime_keys[:6])}")
        suggested_commands = [str(x) for x in list(workspace.get("suggested_commands") or []) if str(x).strip()]
        if suggested_commands:
            lines.append(f"Suggested commands: {', '.join(suggested_commands[:3])}")
        starter_files = [str(x) for x in list(workspace.get("starter_files") or []) if str(x).strip()]
        if starter_files:
            lines.append(f"Starter files: {', '.join(starter_files[:4])}")
        skill_hint = dict(snapshot.get("metadata") or {}).get("skill_expansion") or {}
        health = dict(snapshot.get("metadata") or {}).get("environment_health") or {}
        benchmark_pack = dict(snapshot.get("metadata") or {}).get("benchmark_pack") or {}
        scorecard = dict(snapshot.get("metadata") or {}).get("last_scorecard") or {}
        repo_map = dict(snapshot.get("metadata") or {}).get("repo_map") or {}
        coding_memory = dict(snapshot.get("metadata") or {}).get("coding_memory") or {}
        active_job = dict(snapshot.get("metadata") or {}).get("active_job") or {}
        prompt_line = build_skill_gap_prompt(skill_hint if isinstance(skill_hint, dict) else {})
        if prompt_line:
            lines.append(f"Optional upgrade: {prompt_line}")
        if health.get("summary"):
            lines.append(f"Environment: {health.get('summary')}")
        if scorecard.get("summary"):
            lines.append(f"Verify loop: {scorecard.get('summary')}")
        if repo_map.get("summary"):
            lines.append(f"Repo map: {repo_map.get('summary')}")
        if active_job.get("scorecard"):
            lines.append(f"Job loop: {dict(active_job.get('scorecard') or {}).get('summary')}")
        if coding_memory.get("summary"):
            lines.append(f"Context memory: {coding_memory.get('summary')}")
        if benchmark_pack.get("label"):
            lines.append(f"Benchmark pack: {benchmark_pack.get('label')} [{benchmark_pack.get('profile_key') or language}]")
        next_actions = [str(x) for x in list(snapshot.get("next_actions") or []) if str(x).strip()]
        if next_actions:
            lines.append(f"Next best step: {next_actions[0]}")
        else:
            lines.append("Next best step: inspect the relevant files, sketch the patch, then run the lightest useful checks for this workspace.")
        return "\n".join(lines)

    def list_language_profiles(self) -> list[dict[str, Any]]:
        return [row for row in list_language_profiles() if str(row.get("key") or "") in set(CODING_SUPPORTED_PROFILES)]

    def _should_resume_active_session(
        self,
        active: dict[str, Any] | None,
        *,
        requested_profile_key: str,
        requested_objective: str,
        preferred_workspace: str,
        force_open: bool,
    ) -> bool:
        if not isinstance(active, dict) or str(active.get("status") or "").lower() != "active":
            return False
        workspace = dict(active.get("workspace") or {})
        active_profile_key = str(workspace.get("profile_key") or workspace.get("language") or "python").strip().lower() or "python"
        if active_profile_key != str(requested_profile_key or "python").strip().lower():
            return False
        if preferred_workspace:
            root_text = str(workspace.get("root_path") or "").replace("\\", "/").lower()
            preferred_text = str(preferred_workspace or "").replace("\\", "/").lower()
            if preferred_text and preferred_text not in root_text:
                return False
        if force_open and requested_objective:
            active_prompt = str(active.get("last_prompt") or active.get("objective") or "").strip().lower()
            if active_prompt and active_prompt != str(requested_objective or "").strip().lower():
                return False
        return True

    def _next_actions(
        self,
        *,
        profile_key: str,
        workspace: dict[str, Any],
        objective: str,
        skill_hint: dict[str, Any] | None = None,
        repo_map: dict[str, Any] | None = None,
        active_job: dict[str, Any] | None = None,
    ) -> list[str]:
        profile = get_language_profile(profile_key)
        repo_payload = dict(repo_map or {})
        job_payload = dict(active_job or {})
        focus_files = [str(item) for item in list(repo_payload.get("focus_files") or []) if str(item).strip()]
        actions = [
            f"Inspect {workspace.get('entrypoint') or profile.entrypoint} and outline the smallest viable patch.",
            "List the relevant files before editing so the plan stays grounded in the workspace.",
        ]
        run_command = str(workspace.get("run_command") or "").strip()
        test_command = str(workspace.get("test_command") or "").strip()
        if objective:
            actions.insert(0, f"Translate the objective into a short plan for this {profile.display_name.lower()} workspace.")
        if focus_files:
            actions.insert(1, f"Start with the repo focus files: {', '.join(focus_files[:3])}.")
        if run_command:
            actions.append(f"Use `{run_command}` only after the first patch is in place.")
        if test_command:
            actions.append(f"Use `{test_command}` as the lightest verification pass.")
        if isinstance(skill_hint, dict) and skill_hint.get("capability") and bool(skill_hint.get("proposal_ready", True)):
            actions.append(f"If the task outgrows the current toolbox, draft a skill for {skill_hint['capability']}.")
        if job_payload.get("scorecard"):
            actions.extend([str(item) for item in list(dict(job_payload.get("scorecard") or {}).get("next_actions") or []) if str(item).strip()][:2])
        return actions[:4]

    def _skill_expansion_hint(self, *, objective: str, workspace: dict[str, Any], user_id: str, source: str) -> dict[str, Any] | None:
        available_keys = {
            str(row.get("key") or "").strip().lower()
            for row in list(workspace.get("available_runtimes") or [])
            if bool(row.get("available"))
        }
        detected = detect_skill_gap(
            objective,
            profile_key=str(workspace.get("profile_key") or workspace.get("language") or "python"),
            available_runtime_keys=available_keys,
        )
        if not isinstance(detected, dict) or not detected:
            return None
        suggested = self.skill_forge.suggest_skill_gap(
            prompt=objective,
            user_id=str(user_id or "default_user"),
            source=str(source or "coding_mode"),
            capability=str(detected.get("capability") or ""),
            profile_key=str(workspace.get("profile_key") or workspace.get("language") or "python"),
            available_runtime_keys=available_keys,
        )
        if isinstance(suggested, dict) and suggested:
            return {**dict(detected), **dict(suggested)}
        return dict(detected)

    def open_session(
        self,
        *,
        user_id: str,
        source: str,
        objective: str = "",
        title: str = "",
        preferred_workspace: str = "",
        metadata: dict[str, Any] | None = None,
        resume_active: bool = True,
    ) -> dict[str, Any]:
        safe_user = str(user_id or "default_user").strip() or "default_user"
        cleaned_objective = _clean_objective(objective)
        metadata_dict = dict(metadata or {})
        requested_language = str(metadata_dict.get("language") or metadata_dict.get("profile_key") or "").strip().lower()
        profile = infer_language_profile(cleaned_objective or requested_language, default_key=requested_language or CODING_DEFAULT_LANGUAGE)
        if resume_active:
            active = self.store.get_active_session(safe_user)
            if self._should_resume_active_session(
                active,
                requested_profile_key=profile.key,
                requested_objective=cleaned_objective,
                preferred_workspace=preferred_workspace,
                force_open=bool(metadata_dict.get("force_open", False)),
            ):
                if cleaned_objective:
                    workspace_dict = dict(active.get("workspace") or {})
                    workspace_root = str(workspace_dict.get("root_path") or "").strip()
                    health = build_environment_health(Path(workspace_root)) if workspace_root else {}
                    benchmark_pack = get_repo_task_benchmark_pack(profile.key, health=health) if health else {}
                    repo_map = build_repo_map(Path(workspace_root), objective=cleaned_objective) if workspace_root else {}
                    active_job = self.job_store.start_or_resume_job(
                        session_id=str(active.get("session_id") or ""),
                        objective=cleaned_objective,
                        workspace_root=workspace_root,
                        profile_key=profile.key,
                        repo_focus_files=list(repo_map.get("focus_files") or []),
                    ) if workspace_root and str(active.get("session_id") or "").strip() else {}
                    coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
                    skill_hint = self._skill_expansion_hint(
                        objective=cleaned_objective,
                        workspace=dict(active.get("workspace") or {}),
                        user_id=safe_user,
                        source=source,
                    )
                    active["last_prompt"] = cleaned_objective
                    active["objective"] = cleaned_objective
                    active["updated_at"] = _now_iso()
                    active["metadata"] = {**dict(active.get("metadata") or {}), **metadata_dict, "language_profile": profile.to_dict()}
                    active["metadata"]["skill_expansion"] = skill_hint or {}
                    active["metadata"]["environment_health"] = health or {}
                    active["metadata"]["benchmark_pack"] = benchmark_pack or {}
                    active["metadata"]["repo_map"] = repo_map or {}
                    active["metadata"]["active_job"] = active_job or {}
                    active["metadata"]["coding_memory"] = coding_memory or {}
                    active["next_actions"] = self._next_actions(
                        profile_key=profile.key,
                        workspace=dict(active.get("workspace") or {}),
                        objective=cleaned_objective,
                        skill_hint=skill_hint,
                        repo_map=repo_map,
                        active_job=active_job,
                    )
                    scratchpad, compaction_summary = self._build_compaction_state(
                        active,
                        repo_map=repo_map,
                        health=health,
                        active_job=active_job,
                        coding_memory=coding_memory,
                    )
                    active["metadata"]["scratchpad"] = scratchpad
                    active["metadata"]["compaction_summary"] = compaction_summary
                    active["welcome_text"] = self.build_welcome_text(active)
                    self.store.write_session(active)
                return active

        title_text = str(title or "").strip() or self.workspace_manager.build_title(cleaned_objective or "Coding Session")
        workspace_dict = self.workspace_manager.ensure_workspace(
            user_id=safe_user,
            title=title_text,
            preferred_slug=preferred_workspace,
            language=requested_language or profile.key,
            profile_key=profile.key,
            metadata={**metadata_dict, "language_profile": profile.to_dict()},
            sandbox_backend=str(metadata_dict.get("sandbox_backend") or ""),
            source_repo_root=str(metadata_dict.get("source_repo_root") or metadata_dict.get("repo_root") or ""),
        )
        workspace = CodingWorkspaceSnapshot(**workspace_dict)
        now_iso = _now_iso()
        workspace_root = str(workspace_dict.get("root_path") or "").strip()
        health = build_environment_health(Path(workspace_root)) if workspace_root else {}
        benchmark_pack = get_repo_task_benchmark_pack(profile.key, health=health) if health else {}
        repo_map = build_repo_map(Path(workspace_root), objective=cleaned_objective) if workspace_root else {}
        skill_hint = self._skill_expansion_hint(
            objective=cleaned_objective,
            workspace=workspace_dict,
            user_id=safe_user,
            source=source,
        )
        next_actions = self._next_actions(profile_key=profile.key, workspace=workspace_dict, objective=cleaned_objective, skill_hint=skill_hint, repo_map=repo_map)
        session = CodingSessionSnapshot(
            session_id=_session_id(safe_user),
            user_id=safe_user,
            source=str(source or "chat").strip().lower() or "chat",
            title=title_text,
            objective=cleaned_objective,
            status="active",
            coding_model=self.coding_model,
            agent_profile=self.agent_profile,
            workspace=workspace,
            last_prompt=cleaned_objective,
            turn_count=0,
            tags=["coding", workspace.language, workspace.profile_key, self.agent_profile],
            next_actions=next_actions,
            metadata={
                **metadata_dict,
                "language_profile": profile.to_dict(),
                "available_runtime_keys": [
                    str(row.get("key") or "")
                    for row in list(workspace_dict.get("available_runtimes") or [])
                    if bool(row.get("available"))
                ],
                "workspace_markers": list(workspace_dict.get("workspace_markers") or []),
                "skill_expansion": skill_hint or {},
                "environment_health": health or {},
                "benchmark_pack": benchmark_pack or {},
            },
            created_at=now_iso,
            updated_at=now_iso,
        )
        active_job = self.job_store.start_or_resume_job(
            session_id=session.session_id,
            objective=cleaned_objective,
            workspace_root=workspace_root,
            profile_key=profile.key,
            repo_focus_files=list(repo_map.get("focus_files") or []),
        ) if workspace_root else {}
        coding_memory = build_project_context_memory(repo_map=repo_map, health=health, active_job=active_job)
        session.next_actions = self._next_actions(
            profile_key=profile.key,
            workspace=workspace_dict,
            objective=cleaned_objective,
            skill_hint=skill_hint,
            repo_map=repo_map,
            active_job=active_job,
        )
        session.metadata["repo_map"] = repo_map or {}
        session.metadata["active_job"] = active_job or {}
        session.metadata["coding_memory"] = coding_memory or {}
        payload = session.to_dict()
        scratchpad, compaction_summary = self._build_compaction_state(
            payload,
            repo_map=repo_map,
            health=health,
            active_job=active_job,
            coding_memory=coding_memory,
        )
        payload.setdefault("metadata", {})
        payload["metadata"]["scratchpad"] = scratchpad
        payload["metadata"]["compaction_summary"] = compaction_summary
        payload["welcome_text"] = self.build_welcome_text(payload)
        self.store.write_session(payload)
        return payload

    def list_sessions(self, *, user_id: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        return self.store.list_sessions(user_id=user_id, limit=limit)
