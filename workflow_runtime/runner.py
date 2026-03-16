from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from workflow_runtime.guard import WorkflowValidationError, compile_workflow_script
from workflow_runtime.manifests import WorkflowManifest, normalize_manifest
from workflow_runtime.store import WorkflowRunStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, max_len: int = 600) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _dedupe(items: list[Any]) -> list[str]:
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


def new_workflow_run_id(prefix: str = "workflow") -> str:
    stem = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(prefix or "workflow"))[:40] or "workflow"
    return f"{stem}_{uuid.uuid4().hex[:12]}"


def build_workflow_thread_id(thread_id: str, run_id: str) -> str:
    base = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(thread_id or "general"))[:80] or "general"
    run = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(run_id or "workflow"))[:80] or "workflow"
    return f"{base}::workflow::{run}"


@dataclass
class WorkflowRunSpec:
    workflow_id: str
    name: str
    script: str
    user_id: str
    thread_id: str
    allowed_tools: list[str]
    backend: str = "local"
    timeout_seconds: int = 60
    max_tool_calls: int = 8
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_turn_id: int | None = None
    parent_session_id: str = ""
    run_id: str = field(default_factory=lambda: new_workflow_run_id("workflow"))
    child_thread_id: str = ""

    def __post_init__(self) -> None:
        self.workflow_id = str(self.workflow_id or "workflow").strip() or "workflow"
        self.name = str(self.name or self.workflow_id).strip() or self.workflow_id
        self.script = str(self.script or "")
        self.user_id = str(self.user_id or "default_user").strip() or "default_user"
        self.thread_id = str(self.thread_id or "general").strip() or "general"
        self.allowed_tools = _dedupe(list(self.allowed_tools or []))
        self.backend = str(self.backend or "local").strip().lower() or "local"
        self.timeout_seconds = max(5, min(int(self.timeout_seconds or 60), 900))
        self.max_tool_calls = max(1, min(int(self.max_tool_calls or 8), 100))
        self.inputs = dict(self.inputs or {})
        self.metadata = dict(self.metadata or {})
        self.parent_session_id = str(self.parent_session_id or "")
        self.run_id = str(self.run_id or new_workflow_run_id(self.workflow_id))
        if not self.child_thread_id:
            self.child_thread_id = build_workflow_thread_id(self.thread_id, self.run_id)
        else:
            self.child_thread_id = str(self.child_thread_id)


class _WorkflowToolAPI:
    def __init__(
        self,
        *,
        call_tool,
        allowed_tools: list[str],
        max_tool_calls: int,
        tick,
    ) -> None:
        self._call_tool = call_tool
        self._allowed_tools = {str(x).strip().lower() for x in list(allowed_tools or []) if str(x).strip()}
        self._max_tool_calls = max(1, int(max_tool_calls or 1))
        self._tick = tick
        self.calls: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self._tool_call_count = 0

    def __call__(self, tool_name: str, args: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self._tick()
        name = str(tool_name or "").strip()
        if not name:
            raise WorkflowValidationError("Workflow tool name is required")
        if self._allowed_tools and name.lower() not in self._allowed_tools:
            raise WorkflowValidationError(f"Workflow tool is not allowlisted: {name}")
        payload = dict(args or {})
        if kwargs:
            payload.update(kwargs)
        self._tool_call_count += 1
        if self._tool_call_count > self._max_tool_calls:
            raise WorkflowValidationError("Workflow exceeded max_tool_calls budget")
        started = time.perf_counter()
        output = self._call_tool(name, payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status = "ok" if not isinstance(output, dict) else str(output.get("status") or ("ok" if bool(output.get("ok", True)) else "failed"))
        self.calls.append(
            {
                "tool": name,
                "status": status,
                "detail": _safe_text(str(output.get("error") or output.get("formatted") or output.get("markdown") or output), max_len=240)
                if isinstance(output, dict)
                else _safe_text(output, max_len=240),
                "elapsed_ms": elapsed_ms,
            }
        )
        return output

    def emit(self, message: Any, payload: Any = None) -> None:
        self._tick()
        self.notes.append({"message": _safe_text(message, max_len=300), "payload": payload})


class RestrictedWorkflowRunner:
    def __init__(
        self,
        *,
        runtime: Any,
        state_store: Any = None,
        run_store: WorkflowRunStore | None = None,
    ) -> None:
        self.runtime = runtime
        self.state_store = state_store
        self.run_store = run_store or WorkflowRunStore()

    def _build_snapshot(
        self,
        spec: WorkflowRunSpec,
        *,
        status: str,
        summary: str = "",
        result: Any = None,
        notes: list[dict[str, Any]] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        error: str = "",
        started_at: str = "",
        completed_at: str = "",
    ) -> dict[str, Any]:
        return {
            "run_id": str(spec.run_id),
            "workflow_id": str(spec.workflow_id),
            "name": str(spec.name),
            "user_id": str(spec.user_id),
            "thread_id": str(spec.thread_id),
            "child_thread_id": str(spec.child_thread_id),
            "status": str(status),
            "allowed_tools": list(spec.allowed_tools or []),
            "backend": str(spec.backend),
            "timeout_seconds": int(spec.timeout_seconds),
            "max_tool_calls": int(spec.max_tool_calls),
            "inputs": dict(spec.inputs or {}),
            "metadata": dict(spec.metadata or {}),
            "parent_turn_id": spec.parent_turn_id,
            "parent_session_id": str(spec.parent_session_id or ""),
            "summary": _safe_text(summary, max_len=1600),
            "result": result,
            "notes": list(notes or []),
            "tool_events": list(tool_events or []),
            "error": _safe_text(error, max_len=800),
            "started_at": str(started_at or _now_iso()),
            "completed_at": str(completed_at or ""),
            "updated_at": _now_iso(),
        }

    def _write_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self.run_store.write_snapshot(snapshot)

    def _record_parent_event(self, spec: WorkflowRunSpec, *, event_type: str, payload: dict[str, Any]) -> None:
        if self.state_store is None:
            return
        try:
            self.state_store.record_event(
                user_id=str(spec.user_id),
                thread_id=str(spec.thread_id),
                event_type=event_type,
                event_name=str(spec.workflow_id),
                payload=dict(payload or {}),
            )
        except Exception:
            pass

    def _tool_caller(self, spec: WorkflowRunSpec, ctx: dict[str, Any]):
        base_ctx = dict(ctx or {})
        base_ctx.setdefault("user_id", str(spec.user_id))
        base_ctx.setdefault("backend", str(spec.backend))
        base_ctx.setdefault("channel", "workflow")
        base_ctx.setdefault("operation_mode", "read")
        base_ctx.setdefault("max_risk_tier", "LOW")
        if hasattr(self.runtime, "build_workflow_call"):
            return self.runtime.build_workflow_call(allowed_tools=list(spec.allowed_tools or []), ctx=base_ctx)

        def _call(tool_name: str, args: dict[str, Any]) -> Any:
            return self.runtime.run(tool_name, dict(args or {}), dict(base_ctx))

        return _call

    def _summarize_result(self, result: Any, notes: list[dict[str, Any]], tool_events: list[dict[str, Any]]) -> str:
        if isinstance(result, dict):
            if result.get("summary"):
                return _safe_text(result.get("summary"), max_len=1200)
            if result.get("formatted"):
                return _safe_text(result.get("formatted"), max_len=1200)
        if isinstance(result, list) and result:
            return _safe_text(result[0], max_len=600)
        if result is not None and result != "":
            return _safe_text(result, max_len=1200)
        if notes:
            return _safe_text(notes[-1].get("message") or "", max_len=800)
        if tool_events:
            return _safe_text(tool_events[-1].get("detail") or "", max_len=800)
        return "Workflow completed."

    def run_spec(self, spec: WorkflowRunSpec, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        started_at = _now_iso()
        self._write_snapshot(self._build_snapshot(spec, status="running", started_at=started_at))
        self._record_parent_event(
            spec,
            event_type="workflow_started",
            payload={
                "run_id": str(spec.run_id),
                "workflow_id": str(spec.workflow_id),
                "child_thread_id": str(spec.child_thread_id),
                "parent_turn_id": spec.parent_turn_id,
            },
        )

        child_trace = None
        if self.state_store is not None:
            try:
                child_trace = self.state_store.start_turn(
                    user_id=str(spec.user_id),
                    thread_id=str(spec.child_thread_id),
                    user_text=str(spec.name),
                    routing_prompt=str(spec.workflow_id),
                    metadata={
                        "workflow_run_id": str(spec.run_id),
                        "workflow_id": str(spec.workflow_id),
                        "parent_thread_id": str(spec.thread_id),
                        "parent_turn_id": spec.parent_turn_id,
                        "parent_session_id": str(spec.parent_session_id or ""),
                    },
                )
            except Exception:
                child_trace = None

        started = time.perf_counter()
        step_state = {"count": 0}

        def _tick() -> None:
            step_state["count"] += 1
            if (time.perf_counter() - started) > float(spec.timeout_seconds):
                raise WorkflowValidationError("Workflow timed out")
            if step_state["count"] > max(50, int(spec.max_tool_calls) * 25):
                raise WorkflowValidationError("Workflow exceeded step budget")

        tool_api = _WorkflowToolAPI(
            call_tool=self._tool_caller(spec, dict(ctx or {})),
            allowed_tools=list(spec.allowed_tools or []),
            max_tool_calls=int(spec.max_tool_calls),
            tick=_tick,
        )

        safe_builtins = {
            "len": len,
            "min": min,
            "max": max,
            "sorted": sorted,
            "enumerate": enumerate,
            "range": range,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "sum": sum,
            "any": any,
            "all": all,
            "zip": zip,
            "abs": abs,
            "round": round,
        }
        globals_env = {
            "__builtins__": safe_builtins,
            "tool": tool_api,
            "emit": tool_api.emit,
            "_workflow_tick": _tick,
        }
        locals_env = {
            "inputs": dict(spec.inputs or {}),
            "result": None,
        }

        try:
            compiled = compile_workflow_script(spec.script)
            exec(compiled, globals_env, locals_env)
            result = locals_env.get("result")
            completed_at = _now_iso()
            summary = self._summarize_result(result, tool_api.notes, tool_api.calls)
            snapshot = self._build_snapshot(
                spec,
                status="completed",
                summary=summary,
                result=result,
                notes=tool_api.notes,
                tool_events=tool_api.calls,
                started_at=started_at,
                completed_at=completed_at,
            )
            saved = self._write_snapshot(snapshot)
            if self.state_store is not None and child_trace is not None:
                try:
                    self.state_store.finish_turn(
                        trace=child_trace,
                        assistant_text=str(summary or ""),
                        status="completed",
                        route="workflow",
                        model_name="workflow_runner",
                        routing_prompt=str(spec.workflow_id),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        tool_events=list(tool_api.calls or []),
                        metadata={"workflow_run_id": str(spec.run_id), "workflow_id": str(spec.workflow_id)},
                    )
                except Exception:
                    pass
            self._record_parent_event(
                spec,
                event_type="workflow_completed",
                payload={
                    "run_id": str(spec.run_id),
                    "workflow_id": str(spec.workflow_id),
                    "status": "completed",
                    "summary": str(saved.get("summary") or ""),
                    "child_thread_id": str(spec.child_thread_id),
                },
            )
            return saved
        except Exception as exc:
            completed_at = _now_iso()
            error_text = f"{type(exc).__name__}: {exc}"
            snapshot = self._build_snapshot(
                spec,
                status="failed",
                summary="Workflow execution failed.",
                error=error_text,
                notes=tool_api.notes,
                tool_events=tool_api.calls,
                started_at=started_at,
                completed_at=completed_at,
            )
            saved = self._write_snapshot(snapshot)
            if self.state_store is not None and child_trace is not None:
                try:
                    self.state_store.finish_turn(
                        trace=child_trace,
                        assistant_text=error_text,
                        status="failed",
                        route="workflow",
                        model_name="workflow_runner",
                        routing_prompt=str(spec.workflow_id),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        tool_events=list(tool_api.calls or []),
                        metadata={"workflow_run_id": str(spec.run_id), "workflow_id": str(spec.workflow_id)},
                    )
                except Exception:
                    pass
            self._record_parent_event(
                spec,
                event_type="workflow_failed",
                payload={
                    "run_id": str(spec.run_id),
                    "workflow_id": str(spec.workflow_id),
                    "status": "failed",
                    "error": str(saved.get("error") or ""),
                    "child_thread_id": str(spec.child_thread_id),
                },
            )
            return saved

    def run_script(
        self,
        *,
        script: str,
        workflow_id: str,
        name: str,
        allowed_tools: list[str],
        user_id: str,
        thread_id: str,
        ctx: dict[str, Any] | None = None,
        backend: str = "local",
        timeout_seconds: int = 60,
        max_tool_calls: int = 8,
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_turn_id: int | None = None,
        parent_session_id: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        spec = WorkflowRunSpec(
            workflow_id=str(workflow_id or "workflow"),
            name=str(name or workflow_id or "workflow"),
            script=str(script or ""),
            user_id=str(user_id or "default_user"),
            thread_id=str(thread_id or "general"),
            allowed_tools=list(allowed_tools or []),
            backend=str(backend or "local"),
            timeout_seconds=int(timeout_seconds or 60),
            max_tool_calls=int(max_tool_calls or 8),
            inputs=dict(inputs or {}),
            metadata=dict(metadata or {}),
            parent_turn_id=parent_turn_id,
            parent_session_id=str(parent_session_id or ""),
            run_id=str(run_id or new_workflow_run_id(workflow_id)),
        )
        return self.run_spec(spec, ctx=ctx)

    def run_manifest(
        self,
        manifest: WorkflowManifest,
        *,
        user_id: str,
        thread_id: str,
        ctx: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_turn_id: int | None = None,
        parent_session_id: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        item = manifest if isinstance(manifest, WorkflowManifest) else normalize_manifest(dict(manifest or {}))
        merged_metadata = dict(item.metadata or {})
        merged_metadata.update(dict(metadata or {}))
        return self.run_script(
            script=item.script,
            workflow_id=item.manifest_id,
            name=item.name,
            allowed_tools=list(item.allowed_tools),
            user_id=user_id,
            thread_id=thread_id,
            ctx=ctx,
            backend=item.backend,
            timeout_seconds=item.timeout_seconds,
            max_tool_calls=item.max_tool_calls,
            inputs=dict(inputs or {}),
            metadata=merged_metadata,
            parent_turn_id=parent_turn_id,
            parent_session_id=parent_session_id,
            run_id=run_id,
        )
