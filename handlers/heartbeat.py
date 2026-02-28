from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from handlers.contracts.base import build_base

PROFILE_PATH = os.path.join("config", "assistant_profile.json")
PERSONA_PATH = os.path.join("config", "personalC.json")
DEFAULT_PERSONA_KEY = "Name: Somi"

DEFAULT_PROFILE: Dict[str, Any] = {
    "active_persona_key": DEFAULT_PERSONA_KEY,
    "proactivity_level": 1,
    "focus_domains": [],
    "privacy_mode": "strict",
    "brief_first_interaction_of_day": False,
    "last_brief_date": None,
    "last_heartbeat_at": None,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today_iso() -> str:
    return _utc_now().date().isoformat()


def _normalize_profile_data(raw: Dict[str, Any]) -> Dict[str, Any]:
    prof = dict(DEFAULT_PROFILE)
    if not isinstance(raw, dict):
        return prof

    active = str(raw.get("active_persona_key") or DEFAULT_PERSONA_KEY).strip() or DEFAULT_PERSONA_KEY

    level = raw.get("proactivity_level", 1)
    try:
        level = int(level)
    except Exception:
        level = 1
    if level not in {0, 1, 2, 3}:
        level = 1

    fdomains = raw.get("focus_domains")
    if not isinstance(fdomains, list):
        fdomains = []
    clean_domains: List[str] = []
    for d in fdomains:
        tag = re.sub(r"[^a-z0-9_-]", "", str(d or "").strip().lower())
        if tag and tag not in clean_domains:
            clean_domains.append(tag)

    pmode = str(raw.get("privacy_mode") or "strict").strip().lower()
    if pmode not in {"strict", "standard"}:
        pmode = "strict"

    last_brief = raw.get("last_brief_date")
    if last_brief is not None:
        last_brief = str(last_brief).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", last_brief):
            last_brief = None

    last_hb = raw.get("last_heartbeat_at")
    if last_hb is not None:
        last_hb = str(last_hb).strip() or None

    prof.update(
        {
            "active_persona_key": active,
            "proactivity_level": level,
            "focus_domains": clean_domains[:7],
            "privacy_mode": pmode,
            "brief_first_interaction_of_day": bool(raw.get("brief_first_interaction_of_day", False)),
            "last_brief_date": last_brief,
            "last_heartbeat_at": last_hb,
        }
    )
    return prof


def load_assistant_profile(path: str = PROFILE_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return dict(DEFAULT_PROFILE)
    return _normalize_profile_data(raw)


def save_assistant_profile(profile: Dict[str, Any], path: str = PROFILE_PATH) -> None:
    base = load_assistant_profile(path)
    base.update(dict(profile or {}))
    final = _normalize_profile_data(base)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_persona_catalog(path: str = PERSONA_PATH) -> Dict[str, Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_active_persona(active_persona_key: str, catalog: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    if active_persona_key in catalog and isinstance(catalog.get(active_persona_key), dict):
        return active_persona_key, dict(catalog[active_persona_key])
    if DEFAULT_PERSONA_KEY in catalog and isinstance(catalog.get(DEFAULT_PERSONA_KEY), dict):
        return DEFAULT_PERSONA_KEY, dict(catalog[DEFAULT_PERSONA_KEY])
    for k, v in catalog.items():
        if isinstance(v, dict):
            return str(k), dict(v)
    return DEFAULT_PERSONA_KEY, {"role": "assistant", "temperature": 0.5, "behaviors": ["helpful"]}


def _status_weight(status: str) -> int:
    return {"blocked": 0, "in_progress": 1, "open": 2}.get(str(status or ""), 3)


def _parse_ts(ts: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _age_days(ts: Any) -> int:
    return max(0, int((_utc_now() - _parse_ts(ts)).total_seconds() // 86400))


def _domain_bonus(tags: List[str], focus_domains: List[str]) -> int:
    return 1 if set(tags or []).intersection(set(focus_domains or [])) else 0


def _sanitize_text(text: str, *, strict: bool) -> Tuple[str, bool]:
    t = str(text or "")
    changed = False
    if strict:
        out = re.sub(r"(?:[A-Za-z]:\\|/)[^\s]{3,}", "[path]", t)
        changed = changed or (out != t)
        t = out
        out = re.sub(r"`[^`]{2,}`", "command preview available", t)
        changed = changed or (out != t)
        t = out
    return t[:280], changed


def _sanitize_list(items: List[str], *, strict: bool, max_len: int) -> Tuple[List[str], bool]:
    out: List[str] = []
    any_changed = False
    for it in list(items or [])[:max_len]:
        s, ch = _sanitize_text(str(it), strict=strict)
        if s:
            out.append(s)
        any_changed = any_changed or ch
    return out, any_changed


def _detect_request_kind(user_text: str) -> Optional[str]:
    t = (user_text or "").strip().lower()
    if t == "/brief":
        return "daily_brief"
    if t == "/heartbeat":
        return "heartbeat_tick"
    if t == "/reminders":
        return "reminder_digest"
    if t == "/profile":
        return "profile_view"
    if re.search(r"\b(daily brief|brief me)\b", t):
        return "daily_brief"
    if re.search(r"\bheartbeat\b", t):
        return "heartbeat_tick"
    if re.search(r"\b(what'?s pending|remind me|reminders?)\b", t):
        return "reminder_digest"
    if re.search(r"\bstatus\b", t) and re.search(r"\b(work|task|thread|plan|pending|progress)\b", t):
        return "reminder_digest"
    return None


def _persona_style(persona: Dict[str, Any]) -> str:
    role = str(persona.get("role") or "assistant").lower()
    behaviors = [str(x).strip().lower() for x in list(persona.get("behaviors") or []) if str(x).strip()]
    if "analyst" in role:
        lead = "Concise analyst pulse"
    elif "companion" in role:
        lead = "Warm companion pulse"
    else:
        lead = "Assistant pulse"
    tone = ", ".join(behaviors[:2]) if behaviors else "steady"
    return f"{lead} ({tone})"


def _open_threads(idx: Dict[str, Any], focus_domains: List[str]) -> List[Dict[str, Any]]:
    rows = [r for r in list(idx.get("recent_open_threads") or []) if str((r or {}).get("status") or "") in {"open", "in_progress", "blocked"}]

    def keyfn(r: Dict[str, Any]):
        return (
            _status_weight(str(r.get("status") or "")),
            -int(_parse_ts(r.get("updated_at") or r.get("timestamp") or "1970-01-01T00:00:00+00:00").timestamp()),
            -_age_days(r.get("updated_at") or r.get("timestamp")),
            -_domain_bonus(list(r.get("tags") or []), focus_domains),
            str(r.get("thread_id") or ""),
        )

    return sorted(rows, key=keyfn)[:7]


def _open_tasks(idx: Dict[str, Any], focus_domains: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    by_thread = idx.get("by_thread_id") or {}
    for tid in sorted(by_thread.keys()):
        for row in list(by_thread.get(tid) or []):
            if str(row.get("type") or "") != "task_state":
                continue
            data = row.get("data") or row.get("content") or {}
            for t in list(data.get("tasks") or []):
                status = str(t.get("status") or "unknown")
                if status not in {"open", "in_progress", "blocked"}:
                    continue
                task_id = str(t.get("task_id") or "")
                if not task_id or task_id in seen:
                    continue
                seen.add(task_id)
                out.append(
                    {
                        "task_id": task_id,
                        "title": str(t.get("title") or "")[:200],
                        "status": status,
                        "age_days": _age_days(t.get("updated_at") or row.get("updated_at") or row.get("timestamp")),
                        "source_artifact_id": str(t.get("source_artifact_id") or "") or None,
                        "tags": list(row.get("tags") or []),
                    }
                )

    out.sort(key=lambda r: (_status_weight(r.get("status") or ""), -int(r.get("age_days") or 0), -_domain_bonus(r.get("tags") or [], focus_domains), str(r.get("task_id") or "")))
    for row in out:
        row.pop("tags", None)
    return out[:10]


class HeartbeatEngine:
    def choose_artifact(
        self,
        *,
        user_text: str,
        route: str,
        idx_snapshot: Dict[str, Any],
        profile: Dict[str, Any],
        active_persona_key: str,
        persona: Dict[str, Any],
        first_interaction_of_day: bool,
    ) -> Optional[Dict[str, Any]]:
        kind = _detect_request_kind(user_text)
        if kind is None and bool(profile.get("brief_first_interaction_of_day")) and int(profile.get("proactivity_level") or 0) >= 2 and first_interaction_of_day:
            if str(profile.get("last_brief_date") or "") != _today_iso() and str(route or "") in {"llm_only", "local_memory_intent"}:
                kind = "daily_brief"

        if kind is None:
            return None

        explicit_command = str(user_text or "").strip().startswith("/")
        if not explicit_command and str(route or "") not in {"llm_only", "local_memory_intent"}:
            return None

        strict = str(profile.get("privacy_mode") or "strict") == "strict"
        focus_domains = list(profile.get("focus_domains") or [])
        open_threads = _open_threads(idx_snapshot, focus_domains)
        open_tasks = _open_tasks(idx_snapshot, focus_domains)

        redactions_applied = False
        persona_style = _persona_style(persona)

        if kind == "profile_view":
            return build_base(
                artifact_type="profile_view",
                inputs={"route": route, "user_query": user_text},
                content={
                    "type": "profile_view",
                    "active_persona_key": active_persona_key,
                    "proactivity_level": int(profile.get("proactivity_level") or 1),
                    "focus_domains": focus_domains,
                    "privacy_mode": str(profile.get("privacy_mode") or "strict"),
                    "brief_first_interaction_of_day": bool(profile.get("brief_first_interaction_of_day")),
                    "last_brief_date": profile.get("last_brief_date"),
                    "last_heartbeat_at": profile.get("last_heartbeat_at"),
                    "no_autonomy": True,
                },
            )

        highlights, changed = _sanitize_list(
            [
                f"{len(open_threads)} open threads surfaced",
                f"{len(open_tasks)} open tasks tracked",
                persona_style,
            ],
            strict=strict,
            max_len=5,
        )
        redactions_applied = redactions_applied or changed

        thread_rows = []
        for r in open_threads[:7]:
            title, ch = _sanitize_text(str(r.get("title") or r.get("thread_id") or "Untitled"), strict=strict)
            redactions_applied = redactions_applied or ch
            thread_rows.append(
                {
                    "thread_id": str(r.get("thread_id") or "")[:120],
                    "title": title,
                    "status": str(r.get("status") or "open"),
                    "last_updated": r.get("updated_at") or r.get("timestamp") or _utc_now().isoformat(),
                }
            )

        suggestions = [
            {
                "title": "Continue highest-priority thread",
                "rationale": "Keeps momentum on blocked/in-progress work.",
                "related_artifact_ids": [x.get("artifact_id") for x in open_threads[:2] if x.get("artifact_id")],
                "requires_execution": False,
            },
            {
                "title": "Update task statuses",
                "rationale": "Status accuracy improves next summaries.",
                "related_artifact_ids": [x.get("source_artifact_id") for x in open_tasks[:2] if x.get("source_artifact_id")],
                "requires_execution": False,
            },
            {
                "title": "If you want, I can propose an execution step (Phase 5 approval required)",
                "rationale": "Execution remains approval-gated.",
                "related_artifact_ids": [],
                "requires_execution": True,
            },
        ]

        if kind == "daily_brief":
            task_rows = []
            for t in open_tasks[:10]:
                title, ch = _sanitize_text(str(t.get("title") or "task"), strict=strict)
                redactions_applied = redactions_applied or ch
                task_rows.append(
                    {
                        "task_id": str(t.get("task_id") or "")[:64],
                        "title": title,
                        "status": str(t.get("status") or "open"),
                        "age_days": int(t.get("age_days") or 0),
                        "source_artifact_id": t.get("source_artifact_id"),
                    }
                )
            return build_base(
                artifact_type="daily_brief",
                inputs={"route": route, "user_query": user_text},
                content={
                    "type": "daily_brief",
                    "date": _today_iso(),
                    "active_persona_key": active_persona_key,
                    "highlights": highlights,
                    "open_threads": thread_rows,
                    "open_tasks": task_rows,
                    "suggestions": suggestions[:7],
                    "risk_notes": ["No autonomous execution.", "Phase 5 approval remains required."],
                    "privacy": {"mode": "strict" if strict else "standard", "redactions_applied": bool(redactions_applied)},
                    "guardrails": {"no_autonomy": True, "phase5_required_for_execution": True},
                    "no_autonomy": True,
                },
            )

        if kind == "heartbeat_tick":
            proposals = [
                {
                    "proposal": s["title"],
                    "related_artifact_ids": s["related_artifact_ids"][:20],
                    "requires_execution": bool(s["requires_execution"]),
                }
                for s in suggestions[:3]
            ]
            return build_base(
                artifact_type="heartbeat_tick",
                inputs={"route": route, "user_query": user_text},
                content={
                    "type": "heartbeat_tick",
                    "tick_id": f"tick_{_today_iso()}_{active_persona_key.replace(' ', '_')[:12]}",
                    "active_persona_key": active_persona_key,
                    "sense": {
                        "signals": [f"open_threads={len(open_threads)}", f"open_tasks={len(open_tasks)}"],
                        "anomalies": ["stale_tasks_detected"] if any(int(t.get("age_days") or 0) >= 14 for t in open_tasks) else [],
                    },
                    "think": {
                        "summary": f"{persona_style}: prioritize blocked items first.",
                        "priorities": [x.get("title") for x in suggestions[:3]],
                    },
                    "propose": proposals[:7],
                    "privacy": {"mode": "strict" if strict else "standard", "redactions_applied": bool(redactions_applied)},
                    "guardrails": {"no_autonomy": True, "phase5_required_for_execution": True},
                    "no_autonomy": True,
                },
            )

        items = []
        for t in open_tasks[:12]:
            title, ch = _sanitize_text(str(t.get("title") or "task"), strict=strict)
            redactions_applied = redactions_applied or ch
            items.append(
                {
                    "title": title,
                    "why_now": "Still open and should be reviewed.",
                    "status": str(t.get("status") or "open"),
                    "related_artifact_ids": [str(t.get("source_artifact_id") or "")] if t.get("source_artifact_id") else [],
                }
            )

        return build_base(
            artifact_type="reminder_digest",
            inputs={"route": route, "user_query": user_text},
            content={
                "type": "reminder_digest",
                "active_persona_key": active_persona_key,
                "items": items[:12],
                "suggested_next_actions": [
                    "Continue thread X",
                    "Update task statuses",
                    "Convert open tasks into a plan artifact",
                    "If you want, I can propose an execution step (Phase 5 approval required)",
                ],
                "privacy": {"mode": "strict" if strict else "standard", "redactions_applied": bool(redactions_applied)},
                "no_autonomy": True,
            },
        )
