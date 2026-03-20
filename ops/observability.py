from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .control_plane import OpsControlPlane


_SYNTHETIC_SIGNAL_RE = re.compile(r"(?:^|[\W_])(breaker|eval|dummy|synthetic|fixture|approval\.tool|risk\.tool|test)(?:$|[\W_])", re.IGNORECASE)
_BENIGN_POLICY_REASON_RE = re.compile(r"not exposed to channel 'heartbeat'", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _average(values: list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), 2)


def _is_synthetic_signal(*parts: Any) -> bool:
    blob = " ".join(str(part or "") for part in parts if str(part or "").strip())
    return bool(_SYNTHETIC_SIGNAL_RE.search(blob))


def _is_benign_policy_event(row: dict[str, Any]) -> bool:
    payload = dict(row.get("payload") or {})
    tool_name = str(payload.get("tool") or "")
    reason = str(row.get("reason") or "")
    if _is_synthetic_signal(tool_name, reason):
        return True
    if tool_name == "research.artifacts" and _BENIGN_POLICY_REASON_RE.search(reason):
        return True
    return False


def _tool_hotspots(tool_metrics: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"latencies": [], "failures": 0, "total": 0, "channels": set()})
    for row in tool_metrics:
        tool_name = str(row.get("tool_name") or "tool").strip() or "tool"
        if _is_synthetic_signal(tool_name, row.get("meta")):
            continue
        bucket = grouped[tool_name]
        bucket["total"] += 1
        bucket["latencies"].append(int(row.get("elapsed_ms") or 0))
        bucket["channels"].add(str(row.get("channel") or "chat"))
        if not bool(row.get("success", False)):
            bucket["failures"] += 1

    ranked: list[dict[str, Any]] = []
    for tool_name, bucket in grouped.items():
        latencies = [int(value or 0) for value in list(bucket.get("latencies") or [])]
        ranked.append(
            {
                "tool_name": tool_name,
                "average_latency_ms": _average(latencies),
                "max_latency_ms": max(latencies) if latencies else 0,
                "failure_count": int(bucket.get("failures") or 0),
                "total": int(bucket.get("total") or 0),
                "failure_rate": round((int(bucket.get("failures") or 0) / max(1, int(bucket.get("total") or 0))), 3),
                "channels": sorted(str(item) for item in list(bucket.get("channels") or []) if str(item).strip()),
            }
        )
    ranked.sort(
        key=lambda row: (
            -float(row.get("average_latency_ms") or 0.0),
            -int(row.get("failure_count") or 0),
            str(row.get("tool_name") or ""),
        )
    )
    return ranked[: max(1, int(limit or 3))]


def _model_hotspots(model_metrics: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"latencies": [], "routes": set(), "statuses": set()})
    for row in model_metrics:
        model_name = str(row.get("model_name") or "model").strip() or "model"
        bucket = grouped[model_name]
        bucket["latencies"].append(int(row.get("latency_ms") or 0))
        bucket["routes"].add(str(row.get("route") or "chat"))
        bucket["statuses"].add(str(row.get("status") or "ok"))

    ranked: list[dict[str, Any]] = []
    for model_name, bucket in grouped.items():
        latencies = [int(value or 0) for value in list(bucket.get("latencies") or [])]
        ranked.append(
            {
                "model_name": model_name,
                "average_latency_ms": _average(latencies),
                "max_latency_ms": max(latencies) if latencies else 0,
                "routes": sorted(str(item) for item in list(bucket.get("routes") or []) if str(item).strip()),
                "statuses": sorted(str(item) for item in list(bucket.get("statuses") or []) if str(item).strip()),
                "total": len(latencies),
            }
        )
    ranked.sort(
        key=lambda row: (
            -float(row.get("average_latency_ms") or 0.0),
            -int(row.get("max_latency_ms") or 0),
            str(row.get("model_name") or ""),
        )
    )
    return ranked[: max(1, int(limit or 3))]


def _failure_hotspots(
    tool_metrics: list[dict[str, Any]],
    recent_events: list[dict[str, Any]],
    background_tasks: dict[str, Any],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}

    def bump(name: str, *, kind: str, detail: str = "", count: int = 1) -> None:
        key = f"{kind}:{name}"
        bucket = scores.setdefault(
            key,
            {"name": name, "kind": kind, "count": 0, "detail": detail},
        )
        bucket["count"] = int(bucket.get("count") or 0) + max(1, int(count or 1))
        if detail and not bucket.get("detail"):
            bucket["detail"] = detail

    for row in tool_metrics:
        if bool(row.get("success", False)):
            continue
        tool_name = str(row.get("tool_name") or "tool").strip() or "tool"
        detail = f"tool failure on {str(row.get('channel') or 'chat')}"
        bump(tool_name, kind="tool", detail=detail)

    for row in recent_events:
        event_type = str(row.get("type") or "").strip().lower()
        if event_type == "background_task_failed":
            payload = dict(row.get("payload") or {})
            bump(
                str(payload.get("task_id") or "background_task"),
                kind="background",
                detail=str(payload.get("last_error") or "background task failed"),
            )
        if event_type == "policy_decision" and str(row.get("decision") or "").strip().lower() == "blocked":
            if _is_benign_policy_event(row):
                continue
            bump(
                str(row.get("surface") or "runtime"),
                kind="policy",
                detail=str(row.get("reason") or "policy blocked action"),
            )

    counts = dict(background_tasks.get("counts") or {})
    retry_ready = int(background_tasks.get("retry_ready_count") or counts.get("retry_ready") or 0)
    failed = int(background_tasks.get("failed_count") or counts.get("failed") or 0)
    if retry_ready > 0:
        bump("background_queue", kind="recovery", detail="tasks waiting for retry or handoff", count=retry_ready)
    if failed > 0:
        bump("background_queue", kind="recovery", detail="tasks failed without clean recovery", count=failed)

    ranked = sorted(scores.values(), key=lambda row: (-int(row.get("count") or 0), str(row.get("name") or "")))
    return ranked[: max(1, int(limit or 4))]


def build_observability_digest(
    ops_snapshot: dict[str, Any],
    *,
    slow_tool_ms: int = 3500,
    slow_model_ms: int = 5000,
) -> dict[str, Any]:
    snapshot = dict(ops_snapshot or {})
    recent_metrics = list(snapshot.get("recent_metrics") or [])
    recent_events = list(snapshot.get("recent_events") or [])
    background_tasks = dict(snapshot.get("background_tasks") or {})
    filtered_events: list[dict[str, Any]] = []
    filtered_policy_counts: dict[str, int] = {}
    for row in recent_events:
        if str(row.get("type") or "").strip().lower() == "policy_decision" and _is_benign_policy_event(row):
            continue
        filtered_events.append(row)
        if str(row.get("type") or "").strip().lower() == "policy_decision":
            decision = str(row.get("decision") or "unknown")
            filtered_policy_counts[decision] = filtered_policy_counts.get(decision, 0) + 1

    recent_events = filtered_events
    policy_counts = filtered_policy_counts

    tool_metrics = [
        row
        for row in recent_metrics
        if str(row.get("metric_type") or "") == "tool"
        and not _is_synthetic_signal(row.get("tool_name"), row.get("meta"))
    ]
    model_metrics = [row for row in recent_metrics if str(row.get("metric_type") or "") == "model"]
    tool_hotspots = _tool_hotspots(tool_metrics)
    model_hotspots = _model_hotspots(model_metrics)
    failure_hotspots = _failure_hotspots(tool_metrics, recent_events, background_tasks)
    recovery_pressure = int(background_tasks.get("retry_ready_count") or 0) + int(background_tasks.get("failed_count") or 0)
    blocked_count = int(policy_counts.get("blocked") or 0)

    alerts: list[str] = []
    recommendations: list[str] = []

    if tool_hotspots and float(tool_hotspots[0].get("average_latency_ms") or 0.0) >= float(slow_tool_ms):
        top = tool_hotspots[0]
        alerts.append(
            f"Slow tool hotspot: {top.get('tool_name')} avg {int(float(top.get('average_latency_ms') or 0.0))}ms"
        )
        recommendations.append(
            f"Review the {top.get('tool_name')} tool path or use a lighter plan when it is not essential."
        )
    if model_hotspots and float(model_hotspots[0].get("average_latency_ms") or 0.0) >= float(slow_model_ms):
        top = model_hotspots[0]
        alerts.append(
            f"Slow model hotspot: {top.get('model_name')} avg {int(float(top.get('average_latency_ms') or 0.0))}ms"
        )
        recommendations.append(
            f"Consider a lighter route or tighter prompt budget when {top.get('model_name')} is on the hot path."
        )
    if failure_hotspots:
        top = failure_hotspots[0]
        alerts.append(f"Failure hotspot: {top.get('kind')}::{top.get('name')} x{top.get('count')}")
        recommendations.append("Inspect the recovery watchlist and recent failures before the next long unattended run.")
    if recovery_pressure > 0:
        recommendations.append("Drain retry-ready or failed background tasks so work does not silently stall.")
    if blocked_count > 0:
        recommendations.append("Check whether the current runtime or autonomy profile is blocking legitimate work too often.")

    deduped_recommendations: list[str] = []
    seen: set[str] = set()
    for item in recommendations:
        text = _safe_text(item, limit=220)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped_recommendations.append(text)

    status = "ready"
    if recovery_pressure > 0 or failure_hotspots:
        status = "warn"
    if recovery_pressure >= 3 or blocked_count >= 4:
        status = "critical"

    slow_tool_count = sum(1 for row in tool_hotspots if float(row.get("average_latency_ms") or 0.0) >= float(slow_tool_ms))
    slow_model_count = sum(1 for row in model_hotspots if float(row.get("average_latency_ms") or 0.0) >= float(slow_model_ms))
    summary_line = (
        f"status={status} | slow_tools={slow_tool_count} | slow_models={slow_model_count} | "
        f"failure_hotspots={len(failure_hotspots)} | recovery_pressure={recovery_pressure} | blocked={blocked_count}"
    )

    return {
        "generated_at": _now_iso(),
        "status": status,
        "summary_line": summary_line,
        "alerts": alerts,
        "alert_count": len(alerts),
        "recommendations": deduped_recommendations,
        "slow_tool_count": slow_tool_count,
        "slow_model_count": slow_model_count,
        "recovery_pressure": recovery_pressure,
        "blocked_policy_count": blocked_count,
        "tool_hotspots": tool_hotspots,
        "model_hotspots": model_hotspots,
        "failure_hotspots": failure_hotspots,
    }


def run_observability_snapshot(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir)
    ops = OpsControlPlane(root_dir=root / "sessions" / "ops")
    snapshot = ops.snapshot(event_limit=20, metric_limit=50)
    digest = build_observability_digest(snapshot)
    return {
        "generated_at": _now_iso(),
        "root_dir": str(root),
        "ok": True,
        "ops_snapshot": snapshot,
        "observability": digest,
    }


def format_observability_snapshot(report: dict[str, Any]) -> str:
    observability = dict(report.get("observability") or {})
    lines = [
        "[Somi Observability]",
        f"- root_dir: {report.get('root_dir', '')}",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- status: {observability.get('status', 'idle')}",
        f"- summary: {observability.get('summary_line', '')}",
    ]
    tool_hotspots = list(observability.get("tool_hotspots") or [])
    model_hotspots = list(observability.get("model_hotspots") or [])
    failure_hotspots = list(observability.get("failure_hotspots") or [])
    lines.append("")
    lines.append("Hotspots:")
    if tool_hotspots:
        top = tool_hotspots[0]
        lines.append(
            f"- tool: {top.get('tool_name', '')} avg={int(float(top.get('average_latency_ms') or 0.0))}ms failures={top.get('failure_count', 0)}"
        )
    else:
        lines.append("- tool: none")
    if model_hotspots:
        top = model_hotspots[0]
        lines.append(
            f"- model: {top.get('model_name', '')} avg={int(float(top.get('average_latency_ms') or 0.0))}ms"
        )
    else:
        lines.append("- model: none")
    if failure_hotspots:
        top = failure_hotspots[0]
        lines.append(f"- failure: {top.get('kind', '')}::{top.get('name', '')} x{top.get('count', 0)}")
    else:
        lines.append("- failure: none")
    recommendations = list(observability.get("recommendations") or [])
    lines.append("")
    lines.append("Recommendations:")
    if not recommendations:
        lines.append("- none")
    else:
        for item in recommendations[:6]:
            lines.append(f"- {_safe_text(item, limit=200)}")
    return "\n".join(lines)
