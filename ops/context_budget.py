from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.history_compaction import COMPACTION_PREFIX
from state import SessionEventStore


WATCH_TURN_THRESHOLD = 12
WARN_TURN_THRESHOLD = 24
WATCH_TOKEN_THRESHOLD = 2800
WARN_TOKEN_THRESHOLD = 5600
SYNTHETIC_USER_IDS = {"stress_user", "regression_user", "benchmark_user", "eval_user", "test_user"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _surface_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if text in {"gui", "desktop", "control_room"}:
        return "gui"
    if text in {"tg", "telegram"}:
        return "telegram"
    return text


def _estimate_tokens(*parts: Any) -> int:
    chars = sum(len(str(part or "")) for part in parts)
    return max(0, int(math.ceil(chars / 4.0)))


def _context_status(turn_count: int, estimated_tokens: int, compaction_count: int) -> tuple[str, str]:
    if turn_count <= 0:
        return "idle", "No turns recorded yet."
    if turn_count >= WARN_TURN_THRESHOLD or estimated_tokens >= WARN_TOKEN_THRESHOLD:
        if compaction_count <= 0:
            return "warn", "Long-running thread has no recent compaction checkpoint."
        return "watch", "Long-running thread is active but compaction is present."
    if turn_count >= WATCH_TURN_THRESHOLD or estimated_tokens >= WATCH_TOKEN_THRESHOLD:
        if compaction_count <= 0:
            return "watch", "Context pressure is rising; a refresh or compaction would help."
        return "ready", "Context pressure is moderate and managed by compaction."
    return "ready", "Context pressure is low."


def _compaction_markers(text: str) -> tuple[int, int]:
    content = str(text or "")
    return content.count("Ledger open loops:"), content.count("Ledger unresolved asks:")


def _entry_from_timeline(session: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    turns = [dict(item or {}) for item in list(timeline.get("turns") or []) if isinstance(item, dict)]
    metadata = dict(session.get("metadata") or {})
    compaction_turns = [
        row for row in turns if str(row.get("assistant_text") or "").strip().startswith(COMPACTION_PREFIX)
    ]
    latest_compaction = compaction_turns[-1] if compaction_turns else {}
    latest_compaction_text = str(latest_compaction.get("assistant_text") or "")
    open_loop_count, unresolved_count = _compaction_markers(latest_compaction_text)
    estimated_tokens = sum(
        _estimate_tokens(
            row.get("user_text"),
            row.get("assistant_text"),
            row.get("routing_prompt"),
        )
        for row in turns
    )
    status, note = _context_status(len(turns), estimated_tokens, len(compaction_turns))
    compacted_at = str(latest_compaction.get("completed_at") or latest_compaction.get("created_at") or "")
    last_route = str(session.get("last_route") or "")
    surface = _surface_label(metadata.get("surface") or metadata.get("platform") or "")
    summary = (
        f"{surface} | turns={len(turns)} | est_tokens={estimated_tokens} | "
        f"compactions={len(compaction_turns)} | route={last_route or '--'}"
    )
    return {
        "thread_id": str(session.get("thread_id") or ""),
        "user_id": str(session.get("user_id") or ""),
        "surface": surface,
        "turn_count": len(turns),
        "estimated_tokens": estimated_tokens,
        "compaction_count": len(compaction_turns),
        "last_compacted_at": compacted_at,
        "last_route": last_route,
        "open_loop_count": open_loop_count,
        "unresolved_count": unresolved_count,
        "status": status,
        "status_note": note,
        "latest_compaction_summary": _clip(latest_compaction_text.replace(COMPACTION_PREFIX, "").strip(), limit=240),
        "summary": _clip(summary, limit=180),
        "last_seen_at": str(session.get("last_seen_at") or ""),
    }


def _is_synthetic_session(session: dict[str, Any], timeline: dict[str, Any]) -> bool:
    user_id = str(session.get("user_id") or "").strip().lower()
    if user_id in SYNTHETIC_USER_IDS:
        return True
    metadata = dict(session.get("metadata") or {})
    if bool(metadata.get("synthetic")) or bool(metadata.get("benchmark")) or bool(metadata.get("eval")):
        return True
    for turn in list(timeline.get("turns") or []):
        if not isinstance(turn, dict):
            continue
        row_meta = dict(turn.get("metadata") or {})
        if bool(row_meta.get("synthetic")) or bool(row_meta.get("benchmark")) or bool(row_meta.get("eval")):
            return True
    return False


def run_context_budget_status(
    root_dir: str | Path = ".",
    *,
    user_id: str | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    root = Path(root_dir)
    state_store = SessionEventStore(db_path=root / "sessions" / "state" / "system_state.sqlite3")
    sessions = state_store.list_sessions(user_id=user_id, limit=max(1, int(limit or 12)))
    entries: list[dict[str, Any]] = []
    latest_compacted_at = ""
    total_tokens = 0
    skipped_session_count = 0
    for session in sessions:
        timeline = state_store.load_session_timeline(
            user_id=str(session.get("user_id") or user_id or "default_user"),
            thread_id=str(session.get("thread_id") or ""),
        )
        if _is_synthetic_session(dict(session), timeline):
            skipped_session_count += 1
            continue
        entry = _entry_from_timeline(dict(session), timeline)
        entries.append(entry)
        total_tokens += int(entry.get("estimated_tokens") or 0)
        compacted_at = str(entry.get("last_compacted_at") or "")
        if compacted_at > latest_compacted_at:
            latest_compacted_at = compacted_at

    severity = {"warn": 0, "watch": 1, "ready": 2, "idle": 3}
    entries.sort(
        key=lambda row: (
            severity.get(str(row.get("status") or "idle"), 9),
            -int(row.get("estimated_tokens") or 0),
            -int(row.get("turn_count") or 0),
            str(row.get("last_seen_at") or ""),
        )
    )

    compacted_session_count = sum(1 for row in entries if int(row.get("compaction_count") or 0) > 0)
    pressure_count = sum(1 for row in entries if str(row.get("status") or "") in {"watch", "warn"})
    warn_count = sum(1 for row in entries if str(row.get("status") or "") == "warn")
    watch_count = sum(1 for row in entries if str(row.get("status") or "") == "watch")
    total_turns = sum(int(row.get("turn_count") or 0) for row in entries)

    status = "idle"
    if entries:
        status = "warn" if warn_count > 0 else ("watch" if watch_count > 0 else "ready")

    recommendations: list[str] = []
    if warn_count > 0:
        recommendations.append(
            "Refresh or continue the flagged long-running threads so Somi can compact and preserve open loops before context quality drifts."
        )
    elif watch_count > 0:
        recommendations.append(
            "Monitor the rising-context threads and let Somi produce a fresh compaction summary if the conversation keeps growing."
        )
    if entries and compacted_session_count <= 0 and pressure_count > 0:
        recommendations.append("No recent compaction summaries were found for the active high-pressure threads.")
    if entries and latest_compacted_at:
        parsed = _parse_iso(latest_compacted_at)
        if parsed is not None:
            age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
            if age_hours >= 24.0:
                recommendations.append("Refresh stale compaction checkpoints so long-running work resumes with current constraints and open loops.")

    summary = (
        f"sessions={len(entries)} "
        f"compacted={compacted_session_count} "
        f"pressure={pressure_count} "
        f"est_tokens={total_tokens}"
    )
    return {
        "ok": status != "warn",
        "status": status,
        "generated_at": _now_iso(),
        "root_dir": str(root),
        "user_id": str(user_id or ""),
        "summary": summary,
        "session_count": len(entries),
        "skipped_session_count": skipped_session_count,
        "turn_count": total_turns,
        "estimated_tokens": total_tokens,
        "compacted_session_count": compacted_session_count,
        "pressure_count": pressure_count,
        "warn_count": warn_count,
        "watch_count": watch_count,
        "latest_compacted_at": latest_compacted_at,
        "recommendations": recommendations,
        "entries": entries[: max(1, int(limit or 12))],
    }


def format_context_budget_status(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Context Budget]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- status: {report.get('status', 'idle')}",
        f"- summary: {report.get('summary', '')}",
        f"- sessions: {report.get('session_count', 0)}",
        f"- skipped_sessions: {report.get('skipped_session_count', 0)}",
        f"- turns: {report.get('turn_count', 0)}",
        f"- estimated_tokens: {report.get('estimated_tokens', 0)}",
        f"- compacted_sessions: {report.get('compacted_session_count', 0)}",
        f"- pressure_threads: {report.get('pressure_count', 0)}",
        f"- latest_compacted_at: {report.get('latest_compacted_at', '') or '--'}",
        "",
        "Threads:",
    ]
    entries = list(report.get("entries") or [])
    if not entries:
        lines.append("- none")
    else:
        for row in entries[:8]:
            lines.append(
                "- "
                + f"{row.get('thread_id') or '--'} [{row.get('status') or 'idle'}] "
                + f"{row.get('summary') or ''}"
            )
    lines.append("")
    lines.append("Recommendations:")
    recommendations = list(report.get("recommendations") or [])
    if not recommendations:
        lines.append("- none")
    else:
        for item in recommendations:
            lines.append(f"- {item}")
    return "\n".join(lines)
