from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from state import SessionEventStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _clip(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _issue(kind: str, message: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": str(kind or "issue"),
        "message": str(message or ""),
        "detail": dict(detail or {}),
    }


def _latest_thread_id(store: SessionEventStore, *, user_id: str) -> str:
    sessions = store.list_sessions(user_id=user_id, limit=1)
    if not sessions:
        return ""
    return str(sessions[0].get("thread_id") or "")


def run_replay_harness(
    root_dir: str | Path = ".",
    *,
    user_id: str = "default_user",
    thread_id: str = "",
    limit_turns: int = 12,
) -> dict[str, Any]:
    root = Path(root_dir)
    store = SessionEventStore(root / "sessions" / "state" / "system_state.sqlite3")
    active_thread_id = str(thread_id or "").strip() or _latest_thread_id(store, user_id=user_id)
    if not active_thread_id:
        return {
            "ok": False,
            "generated_at": _now_iso(),
            "user_id": user_id,
            "thread_id": "",
            "summary": {
                "turn_count": 0,
                "event_count": 0,
                "issue_count": 1,
            },
            "issues": [_issue("missing_session", "No session timeline is available to replay.")],
            "timeline": [],
            "overview": "No session timeline is available to replay.",
        }

    timeline = store.load_session_timeline(user_id=user_id, thread_id=active_thread_id)
    turns = list(timeline.get("turns") or [])
    selected_turns = turns[-max(1, int(limit_turns or 12)) :]
    issues: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    previous_turn_index = 0
    previous_event_ts = ""

    for row in selected_turns:
        turn_index = int(row.get("turn_index") or 0)
        if turn_index <= previous_turn_index:
            issues.append(
                _issue(
                    "turn_order",
                    "Turn indexes are not strictly increasing in the replay timeline.",
                    detail={"turn_index": turn_index, "previous_turn_index": previous_turn_index},
                )
            )
        previous_turn_index = turn_index

        events = list(row.get("events") or [])
        if not events:
            issues.append(
                _issue(
                    "missing_events",
                    "A turn is missing bound events in the state timeline.",
                    detail={"turn_index": turn_index},
                )
            )
        elif str(events[0].get("event_name") or "") != "turn_started":
            issues.append(
                _issue(
                    "turn_start_missing",
                    "A replayed turn does not begin with the expected turn_started event.",
                    detail={"turn_index": turn_index, "first_event": events[0].get("event_name")},
                )
            )

        for event in events:
            event_ts = str(event.get("created_at") or "")
            if previous_event_ts and event_ts and event_ts < previous_event_ts:
                issues.append(
                    _issue(
                        "event_order",
                        "Event timestamps moved backward during replay inspection.",
                        detail={"turn_index": turn_index, "event_ts": event_ts, "previous_event_ts": previous_event_ts},
                    )
                )
            if event_ts:
                previous_event_ts = event_ts

        status = str(row.get("status") or "").strip().lower()
        assistant_text = str(row.get("assistant_text") or "").strip()
        if status in {"completed", "complete", "ok"} and not assistant_text:
            issues.append(
                _issue(
                    "missing_output",
                    "A completed turn has no assistant output in the replay timeline.",
                    detail={"turn_index": turn_index},
                )
            )

        replay_rows.append(
            {
                "turn_index": turn_index,
                "status": status or "unknown",
                "route": str(row.get("route") or ""),
                "model_name": str(row.get("model_name") or ""),
                "user_text": _clip(row.get("user_text"), limit=220),
                "assistant_text": _clip(assistant_text, limit=260),
                "event_count": len(events),
                "events": events,
            }
        )

    issue_count = len(issues)
    event_count = sum(int(item.get("event_count") or 0) for item in replay_rows)
    overview_lines = [
        f"Replay user: {user_id}",
        f"Replay thread: {active_thread_id}",
        f"Turns inspected: {len(replay_rows)}",
        f"Events inspected: {event_count}",
        f"Issues: {issue_count}",
    ]
    for row in replay_rows[:8]:
        overview_lines.append(
            f"- Turn {row.get('turn_index')} [{row.get('status')}] route={row.get('route') or '--'} events={row.get('event_count')}"
        )
        overview_lines.append(f"  User: {row.get('user_text')}")
        if row.get("assistant_text"):
            overview_lines.append(f"  Assistant: {row.get('assistant_text')}")

    return {
        "ok": issue_count == 0,
        "generated_at": _now_iso(),
        "user_id": user_id,
        "thread_id": active_thread_id,
        "summary": {
            "turn_count": len(replay_rows),
            "event_count": event_count,
            "issue_count": issue_count,
        },
        "issues": issues,
        "timeline": replay_rows,
        "overview": "\n".join(overview_lines),
    }


def format_replay_harness(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    lines = [
        "[Somi Replay Harness]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- thread_id: {report.get('thread_id') or '--'}",
        f"- turns: {int(summary.get('turn_count', 0) or 0)}",
        f"- events: {int(summary.get('event_count', 0) or 0)}",
        f"- issues: {int(summary.get('issue_count', 0) or 0)}",
        "",
        str(report.get("overview") or "").strip(),
    ]
    issues = list(report.get("issues") or [])
    if issues:
        lines.extend(["", "Issues:"])
        for row in issues[:12]:
            lines.append(f"- [{row.get('kind', 'issue')}] {row.get('message', '')}")
            detail = dict(row.get("detail") or {})
            if detail:
                lines.append(f"  detail={_safe_json(detail)}")
    return "\n".join(line for line in lines if line is not None).strip() + "\n"
