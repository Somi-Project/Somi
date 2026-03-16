from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import threading
from typing import Any

from runtime.task_graph import load_task_graph, record_subagent_activity, save_task_graph
from subagents.registry import SubagentRegistry
from subagents.specs import SubagentRunSpec
from subagents.store import SubagentStatusStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(value: Any, *, max_len: int = 420) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _dedupe_strings(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(items or []):
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


class SubagentExecutionError(RuntimeError):
    pass


class SubagentExecutor:
    def __init__(
        self,
        *,
        registry: SubagentRegistry | None = None,
        runtime: Any = None,
        state_store: Any = None,
        status_store: SubagentStatusStore | None = None,
        task_graph_root: str = "sessions/task_graph",
        max_workers: int = 3,
    ) -> None:
        self.registry = registry or SubagentRegistry()
        self.runtime = runtime
        self.state_store = state_store
        self.status_store = status_store or SubagentStatusStore()
        self.task_graph_root = str(task_graph_root or "sessions/task_graph")
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers or 1)), thread_name_prefix="somi-subagent")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def _tool_allowed(self, spec: SubagentRunSpec, tool_name: str) -> bool:
        allowed = {str(x or "").strip().lower() for x in list(spec.allowed_tools or []) if str(x or "").strip()}
        if not allowed:
            return True
        return str(tool_name or "").strip().lower() in allowed

    def _build_snapshot(
        self,
        spec: SubagentRunSpec,
        *,
        status: str,
        summary: str = "",
        outputs: list[dict[str, Any]] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        error: str = "",
        started_at: str = "",
        completed_at: str = "",
    ) -> dict[str, Any]:
        profile = self.registry.get(spec.profile_key)
        return {
            "run_id": str(spec.run_id),
            "profile_key": str(spec.profile_key),
            "profile_name": str(profile.display_name if profile else spec.profile_key),
            "objective": str(spec.objective),
            "user_id": str(spec.user_id),
            "thread_id": str(spec.thread_id),
            "child_thread_id": str(spec.child_thread_id),
            "status": str(status),
            "allowed_tools": list(spec.allowed_tools or []),
            "max_turns": int(spec.max_turns),
            "backend": str(spec.backend),
            "timeout_seconds": int(spec.timeout_seconds),
            "budget_tokens": int(spec.budget_tokens),
            "parent_turn_id": spec.parent_turn_id,
            "parent_session_id": str(spec.parent_session_id or ""),
            "artifact_refs": list(spec.artifact_refs or []),
            "metadata": dict(spec.metadata or {}),
            "summary": _short(summary, max_len=1600),
            "outputs": list(outputs or []),
            "tool_events": list(tool_events or []),
            "error": _short(error, max_len=800),
            "started_at": str(started_at or _now_iso()),
            "completed_at": str(completed_at or ""),
            "updated_at": _now_iso(),
        }

    def _write_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        saved = self.status_store.write_snapshot(snapshot)
        self._update_task_graph(saved)
        return saved

    def _update_task_graph(self, snapshot: dict[str, Any]) -> None:
        try:
            graph = load_task_graph(
                str(snapshot.get("user_id") or "default_user"),
                str(snapshot.get("thread_id") or "general"),
                root_dir=self.task_graph_root,
            )
            graph = record_subagent_activity(
                graph,
                run_id=str(snapshot.get("run_id") or ""),
                profile_key=str(snapshot.get("profile_key") or ""),
                objective=str(snapshot.get("objective") or ""),
                status=str(snapshot.get("status") or ""),
                child_thread_id=str(snapshot.get("child_thread_id") or ""),
                summary=str(snapshot.get("summary") or ""),
                artifact_refs=list(snapshot.get("artifact_refs") or []),
                parent_turn_id=snapshot.get("parent_turn_id"),
            )
            save_task_graph(
                str(snapshot.get("user_id") or "default_user"),
                str(snapshot.get("thread_id") or "general"),
                graph,
                root_dir=self.task_graph_root,
            )
        except Exception:
            pass

    def _record_parent_event(self, spec: SubagentRunSpec, *, event_type: str, payload: dict[str, Any]) -> None:
        if self.state_store is None:
            return
        try:
            self.state_store.record_event(
                user_id=str(spec.user_id),
                thread_id=str(spec.thread_id),
                event_type=event_type,
                event_name=str(spec.profile_key),
                payload=dict(payload or {}),
            )
        except Exception:
            pass

    def _collect_artifact_refs(self, spec: SubagentRunSpec, outputs: list[dict[str, Any]]) -> list[str]:
        refs = list(spec.artifact_refs or [])
        for row in list(outputs or []):
            output = dict(row.get("output") or {})
            artifact = dict(output.get("artifact") or {})
            if artifact.get("artifact_id"):
                refs.append(str(artifact.get("artifact_id")))
        return _dedupe_strings(refs)

    def _summarize_tool_output(self, tool_name: str, output: dict[str, Any]) -> str:
        data = dict(output or {})
        if str(tool_name) == "web_intelligence_stack":
            formatted = str(data.get("formatted") or "").strip()
            if formatted:
                return _short(formatted, max_len=1400)
        if str(tool_name) == "research_artifact_agentpedia":
            markdown = str(data.get("markdown") or "").strip()
            if markdown:
                return _short(markdown, max_len=1400)
        if "stdout" in data or "stderr" in data:
            text = "\n".join(
                x for x in [str(data.get("stdout") or "").strip(), str(data.get("stderr") or "").strip()] if x
            )
            if text:
                return _short(text, max_len=1400)
        if isinstance(data.get("results"), list) and data.get("results"):
            titles = []
            for row in list(data.get("results") or [])[:3]:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or row.get("topic") or row.get("url") or "").strip()
                if title:
                    titles.append(title)
            if titles:
                return _short("; ".join(titles), max_len=600)
        if data.get("markdown"):
            return _short(str(data.get("markdown") or ""), max_len=1200)
        if data.get("formatted"):
            return _short(str(data.get("formatted") or ""), max_len=1200)
        if data.get("error"):
            return _short(str(data.get("error") or ""), max_len=500)
        return _short(str(data or ""), max_len=500)

    def _tool_call(
        self,
        spec: SubagentRunSpec,
        tool_name: str,
        args: dict[str, Any],
        *,
        approved: bool = False,
        max_risk_tier: str = "LOW",
        operation_mode: str = "read",
    ) -> dict[str, Any]:
        if self.runtime is None:
            raise SubagentExecutionError("Subagent runtime is unavailable")
        if not self._tool_allowed(spec, tool_name):
            raise SubagentExecutionError(f"Tool '{tool_name}' is not allowed for subagent {spec.run_id}")
        ctx = {
            "user_id": str(spec.user_id),
            "backend": str(spec.backend),
            "channel": "chat",
            "approved": bool(approved),
            "max_risk_tier": str(max_risk_tier or "LOW"),
            "operation_mode": str(operation_mode or "read"),
            "audit_job_id": f"subagent_{spec.run_id}",
        }
        return dict(self.runtime.run(tool_name, dict(args or {}), ctx))

    def _coding_session_snapshot(self, spec: SubagentRunSpec) -> dict[str, Any] | None:
        if self.runtime is None or not self._tool_allowed(spec, "coding.workspace"):
            return None
        session_id = str((spec.metadata or {}).get("session_id") or "").strip()
        user_id = str(spec.user_id or "").strip()
        try:
            return self._tool_call(
                spec,
                "coding.workspace",
                {"action": "session_status", "session_id": session_id, "user_id": user_id},
                approved=False,
                max_risk_tier="LOW",
                operation_mode="read",
            )
        except Exception:
            return None

    def _coding_plan_output(self, spec: SubagentRunSpec, session_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        objective = str(spec.objective or "")
        plan = [
            f"Inspect the files or modules directly related to: {objective}",
            "Write the smallest safe change that satisfies the request.",
            "Run targeted tests first, then the broader regression checks if they stay cheap.",
        ]
        workspace = dict((session_snapshot or {}).get("session") or {}).get("workspace") or {}
        if workspace:
            plan.insert(0, f"Stay inside workspace: {workspace.get('root_path') or '--'}")
            suggested = [str(x) for x in list(workspace.get("suggested_commands") or []) if str(x).strip()]
            if suggested:
                plan.append(f"Favor workspace-native checks such as: {', '.join(suggested[:2])}")
        skill_hint = dict((session_snapshot or {}).get("session") or {}).get("metadata") or {}
        skill_expansion = dict(skill_hint.get("skill_expansion") or {})
        if skill_expansion.get("capability"):
            plan.append(f"If needed, draft a skill for {skill_expansion['capability']} before forcing unsupported tooling.")
        if spec.artifact_refs:
            plan.append(f"Carry forward referenced artifacts: {', '.join(spec.artifact_refs[:5])}")
        summary = "No approved execution payload was supplied, so the coding worker returned a bounded implementation plan."
        if workspace:
            summary += f" Workspace profile: {workspace.get('profile_key') or workspace.get('language') or 'python'}."
        return {
            "ok": True,
            "mode": "plan_only",
            "plan": plan,
            "summary": summary,
            "session": dict((session_snapshot or {}).get("session") or {}),
        }

    def _run_profile(self, spec: SubagentRunSpec) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        outputs: list[dict[str, Any]] = []
        tool_events: list[dict[str, Any]] = []
        profile_key = str(spec.profile_key)

        def call(tool_name: str, args: dict[str, Any], *, approved: bool = False, max_risk_tier: str = "LOW", operation_mode: str = "read") -> None:
            try:
                output = self._tool_call(
                    spec,
                    tool_name,
                    args,
                    approved=approved,
                    max_risk_tier=max_risk_tier,
                    operation_mode=operation_mode,
                )
                outputs.append({"tool": tool_name, "output": output})
                status = "ok" if bool(output.get("ok", True)) else "failed"
                detail = self._summarize_tool_output(tool_name, output)
                tool_events.append({"tool": tool_name, "status": status, "detail": _short(detail, max_len=240)})
            except Exception as exc:
                outputs.append({"tool": tool_name, "output": {"ok": False, "error": str(exc)}})
                tool_events.append({"tool": tool_name, "status": "failed", "detail": _short(f"{type(exc).__name__}: {exc}", max_len=240)})

        if profile_key == "research_scout":
            call("web_intelligence_stack", {"query": str(spec.objective)})
            if len(outputs) < spec.max_turns and self._tool_allowed(spec, "research_artifact_agentpedia"):
                call("research_artifact_agentpedia", {"action": "agentpedia_search", "query": str(spec.objective)})
        elif profile_key == "data_gatherer":
            image_paths = [str(x) for x in list((spec.metadata or {}).get("image_paths") or []) if str(x).strip()]
            if image_paths and self._tool_allowed(spec, "ocr_stack"):
                call(
                    "ocr_stack",
                    {
                        "action": "run",
                        "mode": str((spec.metadata or {}).get("ocr_mode") or "structured"),
                        "image_paths": image_paths,
                        "options": dict((spec.metadata or {}).get("ocr_options") or {}),
                    },
                )
            elif self._tool_allowed(spec, "web_intelligence_stack"):
                call("web_intelligence_stack", {"query": str(spec.objective)})
        elif profile_key == "coding_worker":
            session_snapshot = self._coding_session_snapshot(spec)
            tool_request = dict((spec.metadata or {}).get("tool_request") or {})
            requested_tool = str(tool_request.get("tool") or "").strip()
            if requested_tool and self._tool_allowed(spec, requested_tool):
                call(
                    requested_tool,
                    dict(tool_request.get("args") or {}),
                    approved=bool(tool_request.get("approved", False)),
                    max_risk_tier=str(tool_request.get("max_risk_tier") or "MEDIUM"),
                    operation_mode=str(tool_request.get("operation_mode") or "execute"),
                )
                if session_snapshot:
                    outputs.insert(0, {"tool": "coding.workspace", "output": session_snapshot})
                    tool_events.insert(0, {"tool": "coding.workspace", "status": "ok", "detail": "session_status"})
            else:
                cli_request = dict((spec.metadata or {}).get("cli_request") or {})
                cli_allowed = bool((spec.metadata or {}).get("allow_cli_exec")) and bool((spec.metadata or {}).get("approved"))
                if cli_request and cli_allowed and self._tool_allowed(spec, "cli.exec"):
                    call("cli.exec", cli_request, approved=True, max_risk_tier="MEDIUM", operation_mode="execute")
                else:
                    output = self._coding_plan_output(spec, session_snapshot=session_snapshot)
                    outputs.append({"tool": "coding_worker.plan", "output": output})
                    tool_events.append({"tool": "coding_worker.plan", "status": "ok", "detail": _short(output.get("summary"), max_len=240)})
        else:
            call("web_intelligence_stack", {"query": str(spec.objective)})

        if not outputs:
            outputs.append({"tool": "subagent", "output": {"ok": False, "error": "No execution path available"}})
            tool_events.append({"tool": "subagent", "status": "failed", "detail": "no_execution_path"})

        summary_parts = []
        for row in outputs[: max(1, int(spec.max_turns or 1))]:
            tool_name = str(row.get("tool") or "subagent")
            summary = self._summarize_tool_output(tool_name, dict(row.get("output") or {}))
            if summary:
                summary_parts.append(f"[{tool_name}] {summary}")
        return outputs, tool_events, "\n\n".join(summary_parts).strip()

    def run(self, spec: SubagentRunSpec) -> dict[str, Any]:
        started_at = _now_iso()
        self._write_snapshot(self._build_snapshot(spec, status="running", started_at=started_at))
        self._record_parent_event(
            spec,
            event_type="subagent_started",
            payload={
                "run_id": str(spec.run_id),
                "profile_key": str(spec.profile_key),
                "objective": str(spec.objective),
                "child_thread_id": str(spec.child_thread_id),
                "parent_turn_id": spec.parent_turn_id,
                "parent_session_id": str(spec.parent_session_id or ""),
            },
        )

        child_trace = None
        if self.state_store is not None:
            try:
                child_trace = self.state_store.start_turn(
                    user_id=str(spec.user_id),
                    thread_id=str(spec.child_thread_id),
                    user_text=str(spec.objective),
                    routing_prompt=str(spec.objective),
                    metadata={
                        "subagent_run_id": str(spec.run_id),
                        "subagent_profile": str(spec.profile_key),
                        "parent_thread_id": str(spec.thread_id),
                        "parent_turn_id": spec.parent_turn_id,
                        "parent_session_id": str(spec.parent_session_id or ""),
                        "artifact_refs": list(spec.artifact_refs or []),
                    },
                )
            except Exception:
                child_trace = None

        try:
            outputs, tool_events, summary = self._run_profile(spec)
            status = "completed"
            if any(str(event.get("status") or "").lower() == "failed" for event in tool_events) and not any(
                str(event.get("status") or "").lower() == "ok" for event in tool_events
            ):
                status = "failed"
            artifact_refs = self._collect_artifact_refs(spec, outputs)
            completed_at = _now_iso()
            if self.state_store is not None and child_trace is not None:
                try:
                    self.state_store.finish_turn(
                        trace=child_trace,
                        assistant_text=str(summary or ""),
                        status=str(status),
                        route="subagent",
                        model_name=f"subagent:{spec.profile_key}",
                        routing_prompt=str(spec.objective),
                        latency_ms=0,
                        tool_events=list(tool_events or []),
                        metadata={"subagent_run_id": str(spec.run_id), "artifact_refs": list(artifact_refs or [])},
                    )
                except Exception:
                    pass
            snapshot = self._build_snapshot(
                spec,
                status=status,
                summary=summary,
                outputs=outputs,
                tool_events=tool_events,
                started_at=started_at,
                completed_at=completed_at,
            )
            snapshot["artifact_refs"] = artifact_refs
            saved = self._write_snapshot(snapshot)
            self._record_parent_event(
                spec,
                event_type="subagent_completed" if status == "completed" else "subagent_failed",
                payload={
                    "run_id": str(spec.run_id),
                    "profile_key": str(spec.profile_key),
                    "status": str(status),
                    "child_thread_id": str(spec.child_thread_id),
                    "summary": str(saved.get("summary") or ""),
                    "artifact_refs": list(saved.get("artifact_refs") or []),
                    "child_session_id": str(getattr(child_trace, "session_id", "") or ""),
                    "child_turn_id": getattr(child_trace, "turn_id", None),
                },
            )
            return saved
        except Exception as exc:
            completed_at = _now_iso()
            if self.state_store is not None and child_trace is not None:
                try:
                    self.state_store.finish_turn(
                        trace=child_trace,
                        assistant_text=str(exc),
                        status="failed",
                        route="subagent",
                        model_name=f"subagent:{spec.profile_key}",
                        routing_prompt=str(spec.objective),
                        latency_ms=0,
                        tool_events=[{"tool": "subagent", "status": "failed", "detail": type(exc).__name__}],
                        metadata={"subagent_run_id": str(spec.run_id)},
                    )
                except Exception:
                    pass
            snapshot = self._build_snapshot(
                spec,
                status="failed",
                summary="Subagent execution failed before completion.",
                error=f"{type(exc).__name__}: {exc}",
                started_at=started_at,
                completed_at=completed_at,
                tool_events=[{"tool": "subagent", "status": "failed", "detail": type(exc).__name__}],
            )
            saved = self._write_snapshot(snapshot)
            self._record_parent_event(
                spec,
                event_type="subagent_failed",
                payload={
                    "run_id": str(spec.run_id),
                    "profile_key": str(spec.profile_key),
                    "status": "failed",
                    "child_thread_id": str(spec.child_thread_id),
                    "error": str(saved.get("error") or ""),
                },
            )
            return saved

    def submit(self, spec: SubagentRunSpec) -> dict[str, Any]:
        queued = self._write_snapshot(self._build_snapshot(spec, status="queued"))
        future = self._pool.submit(lambda: self.run(spec))
        with self._lock:
            self._futures[str(spec.run_id)] = future
        return queued

    def get_status(self, run_id: str) -> dict[str, Any] | None:
        snapshot = self.status_store.load_snapshot(run_id)
        with self._lock:
            future = self._futures.get(str(run_id))
        if future is not None and future.done():
            try:
                snapshot = future.result()
            except Exception:
                snapshot = snapshot or self.status_store.load_snapshot(run_id)
            with self._lock:
                self._futures.pop(str(run_id), None)
        return snapshot

    def list_snapshots(
        self,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.status_store.list_snapshots(user_id=user_id, thread_id=thread_id, statuses=statuses, limit=limit)
