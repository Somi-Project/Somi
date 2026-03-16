from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from runtime.security_guard import (
    normalize_delivery_channel,
    normalize_execution_backend,
    normalize_risk_tier,
    risk_exceeds,
    tool_allows_backend,
    tool_allows_channel,
)


@dataclass
class ToolCallSpec:
    tool_name: str
    args: Dict[str, Any]
    read_only: bool = True
    tag: str = ""


@dataclass
class ToolOrchestrationBudget:
    max_calls: int = 4
    max_elapsed_seconds: float = 18.0
    max_input_chars: int = 4000
    allow_parallel: bool = True


@dataclass
class ToolOrchestrationResult:
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    budget_exhausted: bool = False
    elapsed_ms: int = 0


RetryableCheck = Callable[[Exception], bool]
RunTool = Callable[[str, Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _filter_specs_with_registry(
    specs: List[ToolCallSpec],
    *,
    registry: Any,
    ctx: Dict[str, Any],
) -> tuple[List[ToolCallSpec], List[Dict[str, Any]]]:
    filtered: List[ToolCallSpec] = []
    events: List[Dict[str, Any]] = []
    if registry is None:
        return list(specs or []), events

    backend = normalize_execution_backend(ctx.get("backend") or ctx.get("execution_backend") or "local")
    channel = normalize_delivery_channel(ctx.get("channel") or ctx.get("delivery_channel") or ctx.get("source") or "chat")
    max_risk_tier = normalize_risk_tier(ctx.get("max_risk_tier", "CRITICAL"))

    for spec in list(specs or []):
        entry = None
        try:
            entry = registry.find(spec.tool_name)
        except Exception:
            entry = None
        if not entry:
            events.append({"tool": spec.tool_name, "status": "blocked", "detail": "registry_missing"})
            continue
        risk_tier = normalize_risk_tier(dict(entry.get("policy") or {}).get("risk_tier", "LOW"))
        if not tool_allows_backend(entry, backend):
            events.append({"tool": spec.tool_name, "status": "blocked", "detail": f"backend:{backend}"})
            continue
        if not tool_allows_channel(entry, channel):
            events.append({"tool": spec.tool_name, "status": "blocked", "detail": f"channel:{channel}"})
            continue
        if risk_exceeds(risk_tier, max_risk_tier):
            events.append({"tool": spec.tool_name, "status": "blocked", "detail": f"risk:{risk_tier}>{max_risk_tier}"})
            continue
        filtered.append(spec)

    return filtered, events


async def run_tool_chain(
    *,
    run_tool: RunTool,
    specs: List[ToolCallSpec],
    ctx: Dict[str, Any],
    budget: ToolOrchestrationBudget,
    retryable_check: RetryableCheck | None = None,
    registry: Any | None = None,
) -> ToolOrchestrationResult:
    start = time.perf_counter()
    events: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []

    remaining_specs = list(specs or [])[: max(1, int(budget.max_calls or 1))]
    filtered_specs, registry_events = _filter_specs_with_registry(remaining_specs, registry=registry, ctx=dict(ctx or {}))
    events.extend(registry_events)
    remaining_specs = filtered_specs
    used_chars = 0

    for spec in remaining_specs:
        if (time.perf_counter() - start) > max(0.5, float(budget.max_elapsed_seconds)):
            events.append({"tool": "tool.orchestrator", "status": "budget_exhausted", "detail": "time"})
            return ToolOrchestrationResult(outputs=outputs, events=events, budget_exhausted=True, elapsed_ms=int((time.perf_counter() - start) * 1000))

        chunk = len(str(spec.args or ""))
        if used_chars + chunk > max(200, int(budget.max_input_chars or 200)):
            events.append({"tool": "tool.orchestrator", "status": "budget_exhausted", "detail": "input_chars"})
            return ToolOrchestrationResult(outputs=outputs, events=events, budget_exhausted=True, elapsed_ms=int((time.perf_counter() - start) * 1000))
        used_chars += chunk

        attempts = 0
        last_exc: Exception | None = None
        while attempts < 2:
            attempts += 1
            try:
                out = await run_tool(spec.tool_name, dict(spec.args or {}), dict(ctx or {}))
                outputs.append({"tool": spec.tool_name, "output": out, "tag": spec.tag})
                status = str((out or {}).get("status") or "ok")
                events.append({"tool": spec.tool_name, "status": status, "detail": f"attempt={attempts}"})
                break
            except Exception as exc:
                last_exc = exc
                is_retryable = bool(retryable_check(exc)) if retryable_check is not None else False
                events.append({"tool": spec.tool_name, "status": "error", "detail": f"{type(exc).__name__};retryable={is_retryable}"})
                if not is_retryable:
                    break
                await asyncio.sleep(0.12 * attempts)

        if last_exc is not None and (not outputs or outputs[-1].get("tool") != spec.tool_name):
            continue

        last_output = outputs[-1].get("output") if outputs else {}
        if isinstance(last_output, dict):
            # Chain semantics: stop on first successful response-like output.
            has_payload = bool(last_output.get("formatted") or last_output.get("results") or last_output.get("ok"))
            blocked = bool(last_output.get("_loop_blocked"))
            if has_payload and not blocked:
                break

    return ToolOrchestrationResult(outputs=outputs, events=events, budget_exhausted=False, elapsed_ms=int((time.perf_counter() - start) * 1000))


async def run_parallel_read_only(
    *,
    run_tool: RunTool,
    specs: List[ToolCallSpec],
    ctx: Dict[str, Any],
    budget: ToolOrchestrationBudget,
    registry: Any | None = None,
) -> ToolOrchestrationResult:
    start = time.perf_counter()
    calls = list(specs or [])[: max(1, int(budget.max_calls or 1))]
    events: List[Dict[str, Any]] = []

    filtered_calls, registry_events = _filter_specs_with_registry(calls, registry=registry, ctx=dict(ctx or {}))
    calls = filtered_calls
    events.extend(registry_events)

    if not calls:
        return ToolOrchestrationResult(outputs=[], events=events, elapsed_ms=0)

    if not bool(budget.allow_parallel):
        return await run_tool_chain(run_tool=run_tool, specs=calls, ctx=ctx, budget=budget, registry=registry)

    if not all(bool(c.read_only) for c in calls):
        return await run_tool_chain(run_tool=run_tool, specs=calls, ctx=ctx, budget=budget, registry=registry)

    async def _one(spec: ToolCallSpec) -> Dict[str, Any]:
        try:
            out = await run_tool(spec.tool_name, dict(spec.args or {}), dict(ctx or {}))
            events.append({"tool": spec.tool_name, "status": str((out or {}).get("status") or "ok"), "detail": "parallel"})
            return {"tool": spec.tool_name, "output": out, "tag": spec.tag}
        except Exception as exc:
            events.append({"tool": spec.tool_name, "status": "error", "detail": type(exc).__name__})
            return {"tool": spec.tool_name, "output": {"ok": False, "error": str(exc)}, "tag": spec.tag}

    timeout = max(0.5, float(budget.max_elapsed_seconds or 10.0))
    try:
        outputs = await asyncio.wait_for(asyncio.gather(*[_one(c) for c in calls]), timeout=timeout)
    except Exception:
        outputs = []
        events.append({"tool": "tool.orchestrator", "status": "budget_exhausted", "detail": "parallel_timeout"})
        return ToolOrchestrationResult(outputs=outputs, events=events, budget_exhausted=True, elapsed_ms=int((time.perf_counter() - start) * 1000))

    return ToolOrchestrationResult(outputs=list(outputs), events=events, budget_exhausted=False, elapsed_ms=int((time.perf_counter() - start) * 1000))


async def run_workflow_script(
    *,
    runner: Any,
    script: str,
    workflow_id: str,
    name: str,
    allowed_tools: List[str],
    ctx: Dict[str, Any],
    user_id: str,
    thread_id: str,
    backend: str = "local",
    timeout_seconds: int = 60,
    max_tool_calls: int = 8,
    inputs: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
    parent_turn_id: int | None = None,
    parent_session_id: str = "",
    run_id: str | None = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        runner.run_script,
        script=str(script or ""),
        workflow_id=str(workflow_id or "workflow"),
        name=str(name or workflow_id or "workflow"),
        allowed_tools=list(allowed_tools or []),
        user_id=str(user_id or "default_user"),
        thread_id=str(thread_id or "general"),
        ctx=dict(ctx or {}),
        backend=str(backend or "local"),
        timeout_seconds=int(timeout_seconds or 60),
        max_tool_calls=int(max_tool_calls or 8),
        inputs=dict(inputs or {}),
        metadata=dict(metadata or {}),
        parent_turn_id=parent_turn_id,
        parent_session_id=str(parent_session_id or ""),
        run_id=run_id,
    )


async def run_workflow_manifest(
    *,
    runner: Any,
    manifest: Any,
    ctx: Dict[str, Any],
    user_id: str,
    thread_id: str,
    inputs: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
    parent_turn_id: int | None = None,
    parent_session_id: str = "",
    run_id: str | None = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        runner.run_manifest,
        manifest,
        user_id=str(user_id or "default_user"),
        thread_id=str(thread_id or "general"),
        ctx=dict(ctx or {}),
        inputs=dict(inputs or {}),
        metadata=dict(metadata or {}),
        parent_turn_id=parent_turn_id,
        parent_session_id=str(parent_session_id or ""),
        run_id=run_id,
    )
