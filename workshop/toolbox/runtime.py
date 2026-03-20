from __future__ import annotations

import asyncio
import importlib.util
import re
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from runtime.audit import append_event
from runtime.action_policy import evaluate_action_policy
from runtime.security_guard import (
    normalize_delivery_channel,
    normalize_execution_backend,
)
from runtime.tool_execution import (
    IdempotencyCache,
    build_idempotency_key,
    default_policy,
    execute_with_policy,
)
from workshop.toolbox.registry import ToolRegistry
from ops import OpsControlPlane


class ToolRuntimeError(RuntimeError):
    pass


class InternalToolRuntime:
    """In-process runtime for read-only/internal tool invocations.

    This is intentionally separate from approval-gated execution tickets.
    It is meant for trusted internal routing where the framework itself
    decides to call a tool wrapper around existing capability stacks.
    """

    def __init__(self, registry: ToolRegistry | None = None, ops_control: OpsControlPlane | None = None) -> None:
        self.registry = registry or ToolRegistry()
        self.ops_control = ops_control or OpsControlPlane()
        self._cache: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {}
        self._idempotency_cache = IdempotencyCache()
        self._failure_streak_by_scope: dict[str, int] = {}
        self._cooldown_until_by_scope: dict[str, float] = {}

    def _resolve_entry(self, tool_name: str) -> dict[str, Any]:
        entry = self.registry.find(tool_name)
        if not entry:
            raise ToolRuntimeError(f"Tool not found: {tool_name}")
        return dict(entry)

    def _load_module(
        self,
        tool_name: str,
        entry: dict[str, Any] | None = None,
    ) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
        item = entry or self._resolve_entry(tool_name)
        path = Path(str(item.get("path") or "")) / "tool.py"
        if not path.exists():
            raise ToolRuntimeError(f"tool.py missing for {tool_name}: {path}")

        key = f"{item.get('name')}@{item.get('version')}"
        if key in self._cache:
            return self._cache[key]

        spec = importlib.util.spec_from_file_location(f"somi_tool_{key}", path)
        if spec is None or spec.loader is None:
            raise ToolRuntimeError(f"Could not load tool module: {path}")

        mod = importlib.util.module_from_spec(spec)
        assert isinstance(mod, ModuleType)
        spec.loader.exec_module(mod)

        run_fn = getattr(mod, "run", None)
        if not callable(run_fn):
            raise ToolRuntimeError(f"Tool {tool_name} is missing run(args, ctx)")

        self._cache[key] = run_fn
        return run_fn

    def _audit_job_id(self, ctx: dict[str, Any]) -> str:
        explicit = str(ctx.get("audit_job_id") or "").strip()
        if explicit:
            return re.sub(r"[^a-zA-Z0-9_.-]", "_", explicit)[:96]

        user_id = str(ctx.get("user_id") or "").strip()
        if user_id:
            safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", user_id)[:64]
            return f"tool_runtime_{safe}"

        return ""

    def _audit_append(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        if not str(job_id or "").strip():
            return
        try:
            append_event(job_id, event, data)
        except Exception:
            pass

    def _breaker_scope(self, tool_name: str, runtime_ctx: dict[str, Any]) -> str:
        user_id = str(runtime_ctx.get("user_id") or "").strip()
        if user_id:
            safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", user_id)[:64]
            return f"{tool_name}:{safe}"
        return str(tool_name)

    def _check_circuit_breaker(self, scope: str, tool_name: str) -> None:
        cooldown_until = float(self._cooldown_until_by_scope.get(scope, 0.0) or 0.0)
        now = time.time()
        if cooldown_until > now:
            wait_seconds = max(1, int(cooldown_until - now))
            raise ToolRuntimeError(
                f"Tool {tool_name} is temporarily paused by runtime circuit breaker; retry in ~{wait_seconds}s"
            )

    def _record_failure(self, scope: str, *, threshold: int, cooldown_seconds: float) -> dict[str, Any]:
        streak = int(self._failure_streak_by_scope.get(scope, 0) or 0) + 1
        self._failure_streak_by_scope[scope] = streak
        activated = streak >= max(1, int(threshold))
        cooldown_until = 0.0
        if activated:
            cooldown_until = float(time.time() + max(1.0, float(cooldown_seconds)))
            self._cooldown_until_by_scope[scope] = cooldown_until
            self._failure_streak_by_scope[scope] = 0
        return {
            "failure_streak": streak,
            "breaker_activated": activated,
            "cooldown_until": cooldown_until,
        }

    def _record_success(self, scope: str) -> None:
        self._failure_streak_by_scope.pop(scope, None)
        self._cooldown_until_by_scope.pop(scope, None)

    def _validate_schema(self, tool_name: str, args: dict[str, Any], schema: dict[str, Any]) -> None:
        schema = dict(schema or {})
        if not schema:
            return
        if str(schema.get("type") or "object").strip().lower() not in {"", "object"}:
            return

        if not isinstance(args, dict):
            raise ToolRuntimeError(f"Tool {tool_name} args must be an object")

        properties = dict(schema.get("properties") or {})
        required = [str(x) for x in list(schema.get("required") or []) if str(x).strip()]
        required_set = set(required)
        additional = schema.get("additionalProperties", True)

        missing = [key for key in required if key not in args]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ToolRuntimeError(f"Tool {tool_name} missing required args: {joined}")

        if additional is False:
            unknown = [key for key in args.keys() if key not in properties]
            if unknown:
                joined = ", ".join(sorted(str(x) for x in unknown))
                raise ToolRuntimeError(f"Tool {tool_name} received unsupported args: {joined}")

        type_map: dict[str, tuple[type, ...]] = {
            "string": (str,),
            "number": (int, float),
            "integer": (int,),
            "boolean": (bool,),
            "object": (dict,),
            "array": (list, tuple),
            "null": (type(None),),
        }

        for key, raw in args.items():
            field_schema = dict(properties.get(key) or {})
            expected = field_schema.get("type")
            if raw is None and key not in required_set:
                continue
            if not expected:
                continue
            expected_types = [str(expected)] if isinstance(expected, str) else [str(x) for x in list(expected)]
            matched = False
            for tname in expected_types:
                tname_l = tname.strip().lower()
                py_types = type_map.get(tname_l)
                if not py_types:
                    continue
                if tname_l == "number" and isinstance(raw, bool):
                    continue
                if tname_l == "integer" and isinstance(raw, bool):
                    continue
                if isinstance(raw, py_types):
                    matched = True
                    break
            if not matched:
                expect = "|".join(expected_types)
                got = type(raw).__name__
                raise ToolRuntimeError(f"Tool {tool_name} arg '{key}' expected type {expect}, got {got}")

    def _registry_availability(self, entry: dict[str, Any]) -> dict[str, Any]:
        availability_fn = getattr(self.registry, "availability", None)
        if callable(availability_fn):
            try:
                return dict(availability_fn(entry))
            except Exception:
                return {"ok": True, "issues": []}
        return {"ok": True, "issues": []}

    def _enforce_policy(self, *, tool_name: str, entry: dict[str, Any], runtime_ctx: dict[str, Any], availability: dict[str, Any]) -> dict[str, Any]:
        decision = evaluate_action_policy(
            tool_name=tool_name,
            entry=entry,
            runtime_ctx=runtime_ctx,
            availability=availability,
        )
        if not bool(decision.allowed):
            reason = str(decision.blocked_reason or "policy_blocked")
            if reason == "approval_required":
                raise ToolRuntimeError(f"Tool {tool_name} requires approval before runtime execution")
            if reason.startswith("mode:"):
                requested_mode = reason.split(":", 1)[-1]
                raise ToolRuntimeError(f"Tool {tool_name} is read_only; operation_mode '{requested_mode}' is disallowed")
            if reason.startswith("risk:"):
                raise ToolRuntimeError(
                    f"Tool {tool_name} risk_tier {decision.risk_tier} exceeds allowed max_risk_tier {decision.max_risk_tier}"
                )
            if reason.startswith("unavailable:"):
                raise ToolRuntimeError(f"Tool {tool_name} is unavailable: {reason.split(':', 1)[-1]}")
            if reason.startswith("backend:"):
                raise ToolRuntimeError(f"Tool {tool_name} does not allow backend '{decision.backend}'")
            if reason.startswith("channel:"):
                raise ToolRuntimeError(f"Tool {tool_name} is not exposed to channel '{decision.channel}'")
            raise ToolRuntimeError(f"Tool {tool_name} blocked by action policy: {reason}")

        state = decision.to_dict()
        state.update(
            {
                "backends": list(entry.get("backends") or []),
                "channels": list(entry.get("channels") or []),
                "capabilities": list(entry.get("capabilities") or []),
                "toolsets": list(entry.get("toolsets") or []),
                "exposure": dict(entry.get("exposure") or {}),
            }
        )
        return state

    def _record_policy_decision(
        self,
        *,
        tool_name: str,
        entry: dict[str, Any] | None,
        decision: str,
        reason: str,
        runtime_ctx: dict[str, Any],
        availability: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.ops_control.record_policy_decision(
                surface="tool_runtime",
                decision=decision,
                reason=reason,
                payload={
                    "tool": str(tool_name),
                    "backend": normalize_execution_backend(runtime_ctx.get("backend") or runtime_ctx.get("execution_backend") or "local"),
                    "channel": normalize_delivery_channel(runtime_ctx.get("channel") or runtime_ctx.get("delivery_channel") or runtime_ctx.get("source") or "chat"),
                    "entry": {
                        "risk_tier": str(dict((entry or {}).get("policy") or {}).get("risk_tier") or "LOW"),
                        "requires_approval": bool(dict((entry or {}).get("policy") or {}).get("requires_approval", False)),
                        "toolsets": list((entry or {}).get("toolsets") or []),
                        "action_class": str(dict((entry or {}).get("policy") or {}).get("action_class") or ""),
                    },
                    "availability": dict(availability or {"ok": True, "issues": []}),
                },
            )
        except Exception:
            pass

    def run(self, tool_name: str, args: dict[str, Any], ctx: dict[str, Any] | None = None) -> Any:
        runtime_ctx = dict(ctx or {})
        runtime_args = dict(args or {})

        entry = self._resolve_entry(tool_name)
        self._validate_schema(tool_name, runtime_args, dict(entry.get("input_schema") or {}))
        availability = self._registry_availability(entry)

        breaker_scope = self._breaker_scope(tool_name, runtime_ctx)
        self._check_circuit_breaker(breaker_scope, tool_name)

        fn = self._load_module(tool_name, entry=entry)

        try:
            policy_state = self._enforce_policy(tool_name=tool_name, entry=entry, runtime_ctx=runtime_ctx, availability=availability)
        except Exception as exc:
            self._record_policy_decision(
                tool_name=tool_name,
                entry=entry,
                decision="blocked",
                reason=f"{type(exc).__name__}: {exc}",
                runtime_ctx=runtime_ctx,
                availability=availability,
            )
            raise
        self._record_policy_decision(
            tool_name=tool_name,
            entry=entry,
            decision="allowed",
            reason="policy_pass",
            runtime_ctx=runtime_ctx,
            availability=availability,
        )
        read_only = bool(policy_state.get("read_only", False))
        policy = default_policy(read_only=read_only, ctx=runtime_ctx)

        idempotency_key = ""
        if read_only and bool(runtime_ctx.get("enable_idempotency", True)):
            idempotency_key = str(runtime_ctx.get("idempotency_key") or "").strip()
            if not idempotency_key:
                idempotency_key = build_idempotency_key(tool_name, runtime_args, runtime_ctx)

        audit_job_id = self._audit_job_id(runtime_ctx)
        breaker_threshold = max(1, int(runtime_ctx.get("tool_circuit_breaker_threshold", 4) or 4))
        breaker_cooldown_seconds = max(1.0, float(runtime_ctx.get("tool_circuit_breaker_cooldown_seconds", 45.0) or 45.0))
        self._audit_append(
            audit_job_id,
            "tool_runtime_start",
            {
                "tool": str(tool_name),
                "read_only": read_only,
                "requires_approval": bool(policy_state.get("requires_approval", False)),
                "risk_tier": str(policy_state.get("risk_tier") or "LOW"),
                "max_risk_tier": str(policy_state.get("max_risk_tier") or "CRITICAL"),
                "approved": bool(policy_state.get("approved", False)),
                "backend": str(policy_state.get("backend") or "local"),
                "channel": str(policy_state.get("channel") or "chat"),
                "action_class": str(policy_state.get("action_class") or "read"),
                "approval_required": bool(policy_state.get("approval_required", False)),
                "confirmation_requirement": str(policy_state.get("confirmation_requirement") or "single_click"),
                "preview_required": bool(policy_state.get("preview_required", False)),
                "rollback_advised": bool(policy_state.get("rollback_advised", False)),
                "capabilities": list(policy_state.get("capabilities") or []),
                "toolsets": list(policy_state.get("toolsets") or []),
                "availability_ok": bool(dict(policy_state.get("availability") or {}).get("ok", True)),
                "max_attempts": int(policy.max_attempts),
                "timeout_seconds": float(policy.timeout_seconds),
                "circuit_breaker_threshold": breaker_threshold,
                "circuit_breaker_cooldown_seconds": breaker_cooldown_seconds,
            },
        )

        try:
            outcome = execute_with_policy(
                fn=fn,
                args=runtime_args,
                ctx=runtime_ctx,
                policy=policy,
                cache=self._idempotency_cache,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            breaker_state = self._record_failure(
                breaker_scope,
                threshold=breaker_threshold,
                cooldown_seconds=breaker_cooldown_seconds,
            )
            try:
                self.ops_control.record_tool_metric(
                    tool_name=str(tool_name),
                    success=False,
                    elapsed_ms=0,
                    backend=str(policy_state.get("backend") or "local"),
                    channel=str(policy_state.get("channel") or "chat"),
                    risk_tier=str(policy_state.get("risk_tier") or "LOW"),
                    approved=bool(policy_state.get("approved", False)),
                    meta={
                        "error_type": type(exc).__name__,
                        "failure_streak": int(breaker_state.get("failure_streak", 0)),
                    },
                )
            except Exception:
                pass
            self._audit_append(
                audit_job_id,
                "tool_runtime_failed",
                {
                    "tool": str(tool_name),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failure_streak": int(breaker_state.get("failure_streak", 0)),
                    "breaker_activated": bool(breaker_state.get("breaker_activated", False)),
                    "cooldown_until": float(breaker_state.get("cooldown_until", 0.0)),
                },
            )
            raise ToolRuntimeError(
                f"Tool execution failed for {tool_name}: {type(exc).__name__}: {exc}"
            ) from exc

        self._record_success(breaker_scope)
        try:
            self.ops_control.record_tool_metric(
                tool_name=str(tool_name),
                success=True,
                elapsed_ms=int(outcome.elapsed_ms),
                backend=str(policy_state.get("backend") or "local"),
                channel=str(policy_state.get("channel") or "chat"),
                risk_tier=str(policy_state.get("risk_tier") or "LOW"),
                approved=bool(policy_state.get("approved", False)),
                meta={
                    "attempts": int(outcome.attempts),
                    "cache_hit": bool(outcome.from_cache),
                },
            )
        except Exception:
            pass
        self._audit_append(
            audit_job_id,
            "tool_runtime_success",
            {
                "tool": str(tool_name),
                "attempts": int(outcome.attempts),
                "cache_hit": bool(outcome.from_cache),
                "elapsed_ms": int(outcome.elapsed_ms),
            },
        )

        value = outcome.value
        if isinstance(value, dict):
            out = dict(value)
            meta = dict(out.get("_runtime") or {})
            meta.setdefault("attempts", int(outcome.attempts))
            meta.setdefault("cache_hit", bool(outcome.from_cache))
            meta.setdefault("elapsed_ms", int(outcome.elapsed_ms))
            meta.setdefault(
                    "policy",
                    {
                        "read_only": bool(policy_state.get("read_only", False)),
                        "requires_approval": bool(policy_state.get("requires_approval", False)),
                        "risk_tier": str(policy_state.get("risk_tier") or "LOW"),
                        "max_risk_tier": str(policy_state.get("max_risk_tier") or "CRITICAL"),
                        "approved": bool(policy_state.get("approved", False)),
                        "backend": str(policy_state.get("backend") or "local"),
                        "channel": str(policy_state.get("channel") or "chat"),
                        "action_class": str(policy_state.get("action_class") or "read"),
                        "approval_required": bool(policy_state.get("approval_required", False)),
                        "confirmation_requirement": str(policy_state.get("confirmation_requirement") or "single_click"),
                        "preview_required": bool(policy_state.get("preview_required", False)),
                        "rollback_advised": bool(policy_state.get("rollback_advised", False)),
                        "autonomy_profile": str(policy_state.get("autonomy_profile") or "balanced"),
                        "autonomy_check": dict(policy_state.get("autonomy_check") or {}),
                    },
                )
            meta.setdefault(
                "registry",
                {
                    "capabilities": list(policy_state.get("capabilities") or []),
                    "toolsets": list(policy_state.get("toolsets") or []),
                    "backends": list(policy_state.get("backends") or []),
                    "channels": list(policy_state.get("channels") or []),
                    "exposure": dict(policy_state.get("exposure") or {}),
                    "availability": dict(policy_state.get("availability") or {"ok": True, "issues": []}),
                },
            )
            out["_runtime"] = meta
            return out

        return value

    async def arun(self, tool_name: str, args: dict[str, Any], ctx: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self.run, tool_name, dict(args or {}), dict(ctx or {}))

    def build_workflow_call(
        self,
        *,
        allowed_tools: list[str] | None = None,
        ctx: dict[str, Any] | None = None,
    ):
        allowed = {str(x or "").strip().lower() for x in list(allowed_tools or []) if str(x or "").strip()}
        base_ctx = dict(ctx or {})

        def _call(tool_name: str, args: dict[str, Any] | None = None) -> Any:
            name = str(tool_name or "").strip()
            if not name:
                raise ToolRuntimeError("Workflow tool name is required")
            if allowed and name.lower() not in allowed:
                raise ToolRuntimeError(f"Workflow tool is not allowlisted: {name}")
            return self.run(name, dict(args or {}), dict(base_ctx))

        return _call

















