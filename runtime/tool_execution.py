from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

from runtime.hashing import sha256_text
from runtime.security_guard import normalize_execution_backend


_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="somi_tool_runtime")


@dataclass(frozen=True)
class ToolExecutionPolicy:
    timeout_seconds: float
    max_attempts: int
    retry_backoff_seconds: float
    idempotency_ttl_seconds: float
    retryable_error_markers: tuple[str, ...]


@dataclass(frozen=True)
class ToolExecutionResult:
    value: Any
    attempts: int
    from_cache: bool
    elapsed_ms: int


class IdempotencyCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._rows: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        k = str(key or "").strip()
        if not k:
            return None
        now = time.time()
        with self._lock:
            row = self._rows.get(k)
            if not row:
                return None
            expires_at, value = row
            if expires_at < now:
                self._rows.pop(k, None)
                return None
            return copy.deepcopy(value)

    def set(self, key: str, value: Any, *, ttl_seconds: float) -> None:
        k = str(key or "").strip()
        if not k:
            return
        ttl = max(1.0, float(ttl_seconds or 1.0))
        expires_at = time.time() + ttl
        with self._lock:
            self._rows[k] = (expires_at, copy.deepcopy(value))


def _get_setting(name: str, default: Any) -> Any:
    try:
        from config import settings as settings_module

        return getattr(settings_module, name, default)
    except Exception:
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        out = float(default)
    if out <= 0:
        return float(default)
    return out


def _coerce_int(value: Any, default: int) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    if out <= 0:
        return int(default)
    return out


def _marker_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        out = [str(x).strip().lower() for x in value if str(x).strip()]
        if out:
            return tuple(out)
    return ("timeout", "timed out", "temporarily unavailable", "connection refused")


def default_policy(*, read_only: bool, ctx: dict[str, Any] | None = None) -> ToolExecutionPolicy:
    runtime_ctx = dict(ctx or {})

    default_timeout = _coerce_float(
        _get_setting("TOOL_RUNTIME_DEFAULT_TIMEOUT_SECONDS", 18),
        18.0,
    )
    timeout_seconds = _coerce_float(
        runtime_ctx.get("tool_timeout_seconds", default_timeout),
        default_timeout,
    )

    attempts_setting = (
        "TOOL_RUNTIME_READ_ONLY_MAX_ATTEMPTS"
        if bool(read_only)
        else "TOOL_RUNTIME_MUTATING_MAX_ATTEMPTS"
    )
    default_attempts = _coerce_int(_get_setting(attempts_setting, 2 if read_only else 1), 2 if read_only else 1)
    max_attempts = _coerce_int(runtime_ctx.get("tool_max_attempts", default_attempts), default_attempts)

    backoff_default = _coerce_float(_get_setting("TOOL_RUNTIME_RETRY_BACKOFF_SECONDS", 0.25), 0.25)
    backoff_seconds = _coerce_float(runtime_ctx.get("tool_retry_backoff_seconds", backoff_default), backoff_default)

    ttl_default = _coerce_float(_get_setting("TOOL_RUNTIME_IDEMPOTENCY_TTL_SECONDS", 120), 120)
    idempotency_ttl_seconds = _coerce_float(runtime_ctx.get("tool_idempotency_ttl_seconds", ttl_default), ttl_default)

    marker_default = _marker_tuple(_get_setting("TOOL_RUNTIME_RETRYABLE_ERRORS", ()))
    marker_override = runtime_ctx.get("tool_retryable_errors")
    retryable_error_markers = _marker_tuple(marker_override) if marker_override else marker_default

    return ToolExecutionPolicy(
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        retry_backoff_seconds=backoff_seconds,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
        retryable_error_markers=retryable_error_markers,
    )


def build_idempotency_key(tool_name: str, args: dict[str, Any], ctx: dict[str, Any] | None = None) -> str:
    payload = {
        "tool": str(tool_name or "").strip().lower(),
        "args": dict(args or {}),
        "user_id": str((ctx or {}).get("user_id") or ""),
        "source": str((ctx or {}).get("source") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return sha256_text(raw)


def execution_backend_from_ctx(ctx: dict[str, Any] | None = None, *, default: str = "local") -> str:
    runtime_ctx = dict(ctx or {})
    return normalize_execution_backend(runtime_ctx.get("backend") or runtime_ctx.get("execution_backend") or default)


def _is_retryable(exc: Exception, policy: ToolExecutionPolicy) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in msg for marker in policy.retryable_error_markers)


def execute_with_policy(
    *,
    fn: Callable[[dict[str, Any], dict[str, Any]], Any],
    args: dict[str, Any],
    ctx: dict[str, Any],
    policy: ToolExecutionPolicy,
    cache: IdempotencyCache | None = None,
    idempotency_key: str = "",
) -> ToolExecutionResult:
    start = time.perf_counter()

    key = str(idempotency_key or "").strip()
    if key and cache is not None:
        cached = cache.get(key)
        if cached is not None:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ToolExecutionResult(value=cached, attempts=0, from_cache=True, elapsed_ms=elapsed)

    max_attempts = max(1, int(policy.max_attempts or 1))
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            future = _EXECUTOR.submit(fn, dict(args or {}), dict(ctx or {}))
            value = future.result(timeout=max(0.1, float(policy.timeout_seconds)))
            if key and cache is not None:
                cache.set(key, value, ttl_seconds=float(policy.idempotency_ttl_seconds))
            elapsed = int((time.perf_counter() - start) * 1000)
            return ToolExecutionResult(value=value, attempts=attempt, from_cache=False, elapsed_ms=elapsed)
        except FutureTimeoutError:
            last_error = TimeoutError(
                f"tool execution exceeded timeout ({policy.timeout_seconds:.2f}s)"
            )
            try:
                future.cancel()
            except Exception:
                pass
        except Exception as exc:
            last_error = exc

        if attempt >= max_attempts:
            break
        if last_error is None or not _is_retryable(last_error, policy):
            break

        backoff = max(0.0, float(policy.retry_backoff_seconds)) * float(attempt)
        if backoff > 0:
            time.sleep(backoff)

    if last_error is None:
        last_error = RuntimeError("tool execution failed for unknown reason")
    raise last_error
