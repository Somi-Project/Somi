from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT = Path("sessions/state")


@dataclass
class ActiveItem:
    title: str
    type: str
    status: str
    last_mentioned_ts: str
    short_summary: str


@dataclass
class OpenLoop:
    title: str
    loop_type: str
    status: str = "open"
    created_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UserState:
    user_id: str
    active_items: list[ActiveItem] = field(default_factory=list)
    open_loops: list[OpenLoop] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)
    recent_context_summary: str = ""
    friction_signals: dict[str, int] = field(default_factory=dict)
    scheduled_nudges: list[dict] = field(default_factory=list)


ALLOWED_ACTIVE_TYPES = {
    "project",
    "task",
    "learning topic",
    "problem",
    "health concern",
    "workflow item",
}


def _state_path(user_id: str) -> Path:
    return STATE_ROOT / f"{user_id}.json"


def load_user_state(user_id: str) -> UserState:
    p = _state_path(user_id)
    if not p.exists():
        return UserState(user_id=user_id)
    data = json.loads(p.read_text(encoding="utf-8"))
    return UserState(
        user_id=data.get("user_id", user_id),
        active_items=[ActiveItem(**i) for i in data.get("active_items", [])],
        open_loops=[OpenLoop(**i) for i in data.get("open_loops", [])],
        pending_approvals=list(data.get("pending_approvals", [])),
        recent_context_summary=data.get("recent_context_summary", ""),
        friction_signals=dict(data.get("friction_signals", {})),
        scheduled_nudges=list(data.get("scheduled_nudges", [])),
    )


def save_user_state(state: UserState) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _state_path(state.user_id).write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upsert_active_item(state: UserState, *, title: str, item_type: str, summary: str) -> None:
    typ = item_type if item_type in ALLOWED_ACTIVE_TYPES else "task"
    now = datetime.now(timezone.utc).isoformat()
    for item in state.active_items:
        if item.title.lower() == title.lower():
            item.last_mentioned_ts = now
            item.short_summary = summary or item.short_summary
            return
    state.active_items.append(
        ActiveItem(
            title=title,
            type=typ,
            status="active",
            last_mentioned_ts=now,
            short_summary=summary,
        )
    )
