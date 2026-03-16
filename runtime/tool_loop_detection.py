from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolLoopConfig:
    enabled: bool = False
    history_size: int = 30
    warning_threshold: int = 10
    critical_threshold: int = 20
    global_circuit_breaker_threshold: int = 30
    detect_generic_repeat: bool = True
    detect_no_progress: bool = True
    detect_ping_pong: bool = True


@dataclass(frozen=True)
class LoopDetectionResult:
    stuck: bool
    level: str = ""
    detector: str = ""
    count: int = 0
    message: str = ""
    warning_key: str = ""


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return repr(value)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def hash_tool_call(tool_name: str, args: Any) -> str:
    return _hash_text(f"{tool_name}|{_stable_json(args)}")


def hash_tool_outcome(result: Any = None, error: Any = None) -> str | None:
    if error is not None:
        return "error:" + _hash_text(_stable_json(error))
    if result is None:
        return None
    return _hash_text(_stable_json(result))


def _trim_history(history: list[dict[str, Any]], max_size: int) -> None:
    keep = max(1, int(max_size))
    if len(history) > keep:
        del history[: len(history) - keep]


def record_tool_call(history: list[dict[str, Any]], *, tool_name: str, args: Any, cfg: ToolLoopConfig) -> None:
    history.append(
        {
            "tool_name": tool_name,
            "sig": hash_tool_call(tool_name, args),
            "ts": int(time.time() * 1000),
        }
    )
    _trim_history(history, cfg.history_size)


def record_tool_call_outcome(
    history: list[dict[str, Any]],
    *,
    tool_name: str,
    args: Any,
    result: Any = None,
    error: Any = None,
    cfg: ToolLoopConfig,
) -> None:
    sig = hash_tool_call(tool_name, args)
    out_sig = hash_tool_outcome(result=result, error=error)
    if out_sig is None:
        return

    for row in reversed(history):
        if row.get("tool_name") == tool_name and row.get("sig") == sig and row.get("result_sig") is None:
            row["result_sig"] = out_sig
            _trim_history(history, cfg.history_size)
            return

    history.append(
        {
            "tool_name": tool_name,
            "sig": sig,
            "result_sig": out_sig,
            "ts": int(time.time() * 1000),
        }
    )
    _trim_history(history, cfg.history_size)


def _no_progress_streak(history: list[dict[str, Any]], sig: str) -> tuple[int, str | None]:
    latest: str | None = None
    streak = 0
    for row in reversed(history):
        if row.get("sig") != sig:
            continue
        r_sig = row.get("result_sig")
        if not r_sig:
            continue
        if latest is None:
            latest = str(r_sig)
            streak = 1
            continue
        if str(r_sig) != latest:
            break
        streak += 1
    return streak, latest


def _generic_repeat_count(history: list[dict[str, Any]], sig: str) -> int:
    return sum(1 for row in history if row.get("sig") == sig)


def _ping_pong_streak(history: list[dict[str, Any]], current_sig: str) -> tuple[int, bool]:
    if len(history) < 2:
        return 0, False

    last_sig = str(history[-1].get("sig") or "")
    if not last_sig:
        return 0, False

    other_sig = ""
    for row in reversed(history[:-1]):
        sig = str(row.get("sig") or "")
        if sig and sig != last_sig:
            other_sig = sig
            break
    if not other_sig or current_sig != other_sig:
        return 0, False

    alternating = 0
    expected = last_sig
    for row in reversed(history):
        sig = str(row.get("sig") or "")
        if sig != expected:
            break
        alternating += 1
        expected = other_sig if expected == last_sig else last_sig

    if alternating < 2:
        return 0, False

    pair_hashes: dict[str, set[str]] = {last_sig: set(), other_sig: set()}
    for row in history[-alternating:]:
        sig = str(row.get("sig") or "")
        rs = str(row.get("result_sig") or "")
        if sig in pair_hashes and rs:
            pair_hashes[sig].add(rs)

    no_progress = all(len(v) == 1 for v in pair_hashes.values() if v)
    return alternating + 1, no_progress


def detect_tool_loop(history: list[dict[str, Any]], *, tool_name: str, args: Any, cfg: ToolLoopConfig) -> LoopDetectionResult:
    if not cfg.enabled:
        return LoopDetectionResult(stuck=False)

    sig = hash_tool_call(tool_name, args)

    if cfg.detect_no_progress:
        streak, latest_result = _no_progress_streak(history, sig)
        if streak >= cfg.global_circuit_breaker_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="critical",
                detector="global_circuit_breaker",
                count=streak,
                message=(
                    f"Critical loop guard: '{tool_name}' repeated identical no-progress outcomes "
                    f"{streak} times. Tool call blocked."
                ),
                warning_key=f"global:{tool_name}:{sig}:{latest_result or 'none'}",
            )
        if streak >= cfg.critical_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="critical",
                detector="no_progress",
                count=streak,
                message=(
                    f"Critical loop guard: '{tool_name}' repeated with no progress {streak} times. "
                    "Tool call blocked."
                ),
                warning_key=f"noprogress:{tool_name}:{sig}:{latest_result or 'none'}",
            )
        if streak >= cfg.warning_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="no_progress",
                count=streak,
                message=(
                    f"Loop warning: '{tool_name}' has repeated no-progress results {streak} times."
                ),
                warning_key=f"noprogress:{tool_name}:{sig}:{latest_result or 'none'}",
            )

    if cfg.detect_ping_pong:
        pp_count, pp_no_progress = _ping_pong_streak(history, sig)
        if pp_no_progress and pp_count >= cfg.critical_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="critical",
                detector="ping_pong",
                count=pp_count,
                message=(
                    f"Critical loop guard: alternating call pattern detected ({pp_count} consecutive calls). "
                    "Tool call blocked."
                ),
                warning_key=f"pingpong:{sig}",
            )
        if pp_count >= cfg.warning_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="ping_pong",
                count=pp_count,
                message=f"Loop warning: alternating tool-call pattern detected ({pp_count} consecutive calls).",
                warning_key=f"pingpong:{sig}",
            )

    if cfg.detect_generic_repeat:
        repeated = _generic_repeat_count(history, sig)
        if repeated >= cfg.warning_threshold:
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="generic_repeat",
                count=repeated,
                message=(
                    f"Loop warning: '{tool_name}' with identical arguments appeared {repeated} times recently."
                ),
                warning_key=f"generic:{tool_name}:{sig}",
            )

    return LoopDetectionResult(stuck=False)
