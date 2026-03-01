from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any


BANNED_WORDS = {"lazy", "procrastinate", "you always"}


def _parse_ts(ts: str | None) -> datetime:
    try:
        dt = datetime.fromisoformat(str(ts or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def detect_patterns(items: list[dict[str, Any]], projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    recent30 = [x for x in items if (now - _parse_ts(x.get("updated_at"))).days <= 30]
    recent7 = [x for x in items if (now - _parse_ts(x.get("updated_at"))).days <= 7]

    reopen = [x for x in recent30 if str(x.get("status") or "").lower() == "reopened"]
    if len(reopen) >= 3:
        out.append(_p("reopen_cycle", "Tasks are reopening frequently; tighten acceptance criteria.", reopen, 0.72, "Add a done-definition checklist before closing."))

    overdue = [x for x in recent30 if x.get("due_at") and _parse_ts(x.get("due_at")) < now and str(x.get("status") or "") not in {"done", "closed"}]
    if len(overdue) >= 3:
        out.append(_p("deadline_slip", "Multiple items are overdue in the last 30 days.", overdue, 0.78, "Review estimates and break large tasks into smaller checkpoints."))

    refactor = [x for x in recent7 if "refactor" in set(x.get("tags") or [])]
    if len(refactor) >= 4:
        out.append(_p("refactor_burst", "Refactor work surged this week.", refactor, 0.66, "Reserve a focused refactor block and protect delivery work."))

    threads = [x for x in items if x.get("type") == "thread"]
    recurring = _detect_recurring_reports(threads)
    if recurring:
        out.append(recurring)

    blocked = [x for x in recent30 if str(x.get("status") or "") == "blocked"]
    dep_counts: Counter[str] = Counter()
    dep_ev: defaultdict[str, list[str]] = defaultdict(list)
    for x in blocked:
        dep = next((t for t in list(x.get("tags") or []) if t.startswith("dep:")), None)
        if dep:
            dep_counts[dep] += 1
            dep_ev[dep].append(str(x.get("id") or ""))
    dep, cnt = (dep_counts.most_common(1)[0] if dep_counts else (None, 0))
    if dep and cnt >= 3:
        ev = [x for x in blocked if str(x.get("id") or "") in dep_ev[dep]]
        out.append(_p("blocked_dependency", f"Several tasks are blocked by {dep}.", ev, 0.75, "Escalate the dependency owner and add fallback options."))

    active_tasks = [x for x in items if str(x.get("status") or "") in {"open", "in_progress", "blocked"}]
    active_projects = [p for p in projects if int(p.get("open_items") or 0) > 0]
    if len(active_tasks) >= 5 and len(active_projects) >= 3:
        out.append(_p("context_switching", "Work is spread across many active projects.", active_tasks[:7], 0.7, "Timebox fewer projects this week to reduce switching cost."))

    clean = [p for p in out if not any(b in str(p.get("description") or "").lower() for b in BANNED_WORDS)]
    return sorted(clean, key=lambda x: str(x.get("pattern_id") or ""))


def _detect_recurring_reports(threads: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(threads) < 3:
        return None
    sorted_threads = sorted(threads, key=lambda x: _parse_ts(x.get("updated_at")))
    groups: list[list[dict[str, Any]]] = []
    for row in sorted_threads:
        placed = False
        for g in groups:
            ratio = SequenceMatcher(None, str(g[0].get("title") or ""), str(row.get("title") or "")).ratio()
            if ratio >= 0.72:
                g.append(row)
                placed = True
                break
        if not placed:
            groups.append([row])

    for g in groups:
        if len(g) < 3:
            continue
        deltas = []
        for i in range(1, len(g)):
            deltas.append(abs((_parse_ts(g[i].get("updated_at")) - _parse_ts(g[i - 1].get("updated_at"))).days))
        if deltas and all(5 <= d <= 9 for d in deltas[:3]):
            return _p("recurring_report", "A recurring report-like thread cadence was detected.", g[:5], 0.73, "Template the recurring update and pre-fill key metrics.")
    return None


def _p(kind: str, desc: str, ev_rows: list[dict[str, Any]], conf: float, intervention: str) -> dict[str, Any]:
    return {
        "artifact_type": "pattern_insight",
        "pattern_id": f"pattern_{kind}",
        "pattern_type": kind,
        "description": desc,
        "confidence": max(0.0, min(0.99, conf)),
        "intervention": intervention,
        "evidence_artifact_ids": [str(x.get("id") or "") for x in ev_rows if str(x.get("id") or "")][:20],
    }
