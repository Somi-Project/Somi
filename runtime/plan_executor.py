from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


PLAN_PHASES = ("plan", "act", "verify", "finalize")


@dataclass
class PlanState:
    user_id: str
    thread_id: str
    phase: str
    objective: str
    steps: List[str]
    checks: List[str]
    stop_conditions: Dict[str, Any]
    tool_call_count: int
    no_progress_turns: int
    cycle_count: int
    stop_reason: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(text: Any, *, max_len: int = 220) -> str:
    s = " ".join(str(text or "").strip().split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "..."


def _path(user_id: str, thread_id: str, root_dir: str = "sessions/plan_executor") -> Path:
    uid = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(user_id or "default_user"))[:100]
    tid = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(thread_id or "general"))[:100]
    return Path(root_dir) / f"{uid}__{tid}.json"


def _default_state(user_id: str, thread_id: str) -> Dict[str, Any]:
    return {
        "user_id": str(user_id or "default_user"),
        "thread_id": str(thread_id or "general"),
        "phase": "plan",
        "objective": "",
        "steps": [],
        "checks": [],
        "stop_conditions": {
            "max_tool_calls": 4,
            "max_no_progress_turns": 2,
            "max_cycles": 6,
        },
        "tool_call_count": 0,
        "no_progress_turns": 0,
        "cycle_count": 0,
        "stop_reason": "",
        "updated_at": _now_iso(),
    }


def _extract_steps(text: str, *, max_items: int = 5) -> List[str]:
    out: List[str] = []
    raw = str(text or "")

    for line in raw.splitlines():
        ls = line.strip(" -\t")
        if not ls:
            continue
        if len(ls) < 8:
            continue
        if re.search(r"\b(next|todo|step|plan|verify|check|test|implement|update|fix)\b", ls, flags=re.IGNORECASE):
            out.append(_safe(ls, max_len=160))

    if not out:
        m = re.search(r"\b(?:need to|want to|goal is|objective is)\s+(.+)$", raw, flags=re.IGNORECASE)
        if m:
            base = _safe(m.group(1), max_len=160)
            out.extend([
                f"Clarify success criteria for: {base}",
                f"Execute the highest-impact action for: {base}",
                f"Verify outcome and list remaining risks for: {base}",
            ])

    seen = set()
    deduped: List[str] = []
    for item in out:
        k = item.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def _extract_checks(objective: str) -> List[str]:
    obj = _safe(objective, max_len=120)
    if not obj:
        return [
            "Confirm output matches the user request.",
            "Confirm no unsupported assumptions remain.",
        ]
    return [
        f"Confirm objective coverage: {obj}",
        "Confirm outputs include verification signals or caveats.",
        "Confirm no unresolved blockers are hidden.",
    ]


def load_plan_state(user_id: str, thread_id: str, *, root_dir: str = "sessions/plan_executor") -> Dict[str, Any]:
    p = _path(user_id, thread_id, root_dir=root_dir)
    if not p.exists():
        return _default_state(user_id, thread_id)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _default_state(user_id, thread_id)
    except Exception:
        return _default_state(user_id, thread_id)

    out = _default_state(user_id, thread_id)
    out.update({
        "phase": str(raw.get("phase") or "plan") if str(raw.get("phase") or "plan") in PLAN_PHASES else "plan",
        "objective": _safe(raw.get("objective"), max_len=200),
        "steps": [_safe(x, max_len=180) for x in list(raw.get("steps") or []) if str(x).strip()][:8],
        "checks": [_safe(x, max_len=180) for x in list(raw.get("checks") or []) if str(x).strip()][:8],
        "stop_conditions": dict(raw.get("stop_conditions") or out["stop_conditions"]),
        "tool_call_count": int(raw.get("tool_call_count") or 0),
        "no_progress_turns": int(raw.get("no_progress_turns") or 0),
        "cycle_count": int(raw.get("cycle_count") or 0),
        "stop_reason": _safe(raw.get("stop_reason"), max_len=180),
        "updated_at": str(raw.get("updated_at") or out["updated_at"]),
    })
    return out


def save_plan_state(user_id: str, thread_id: str, state: Dict[str, Any], *, root_dir: str = "sessions/plan_executor") -> Dict[str, Any]:
    p = _path(user_id, thread_id, root_dir=root_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = _default_state(user_id, thread_id)
    out.update({
        "phase": str((state or {}).get("phase") or "plan"),
        "objective": _safe((state or {}).get("objective"), max_len=200),
        "steps": [_safe(x, max_len=180) for x in list((state or {}).get("steps") or []) if str(x).strip()][:8],
        "checks": [_safe(x, max_len=180) for x in list((state or {}).get("checks") or []) if str(x).strip()][:8],
        "stop_conditions": dict((state or {}).get("stop_conditions") or out["stop_conditions"]),
        "tool_call_count": int((state or {}).get("tool_call_count") or 0),
        "no_progress_turns": int((state or {}).get("no_progress_turns") or 0),
        "cycle_count": int((state or {}).get("cycle_count") or 0),
        "stop_reason": _safe((state or {}).get("stop_reason"), max_len=180),
        "updated_at": _now_iso(),
    })
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return out


def ensure_plan_state(
    user_id: str,
    thread_id: str,
    *,
    prompt: str,
    state: Dict[str, Any] | None = None,
    stop_conditions: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    out = dict(state or load_plan_state(user_id, thread_id))
    prompt_s = _safe(prompt, max_len=220)

    if not str(out.get("objective") or "").strip():
        out["objective"] = prompt_s
    if not list(out.get("steps") or []):
        out["steps"] = _extract_steps(prompt_s)
    if not list(out.get("checks") or []):
        out["checks"] = _extract_checks(str(out.get("objective") or ""))

    merged = dict(out.get("stop_conditions") or {})
    if stop_conditions:
        merged.update(dict(stop_conditions))
    merged.setdefault("max_tool_calls", 4)
    merged.setdefault("max_no_progress_turns", 2)
    merged.setdefault("max_cycles", 6)
    out["stop_conditions"] = merged

    phase = str(out.get("phase") or "plan")
    if phase not in PLAN_PHASES:
        out["phase"] = "plan"

    out["updated_at"] = _now_iso()
    return out


def advance_plan_state(
    state: Dict[str, Any],
    *,
    tool_events: List[Dict[str, Any]] | None = None,
    assistant_text: str = "",
) -> Dict[str, Any]:
    out = dict(state or {})
    phase = str(out.get("phase") or "plan")
    stop = dict(out.get("stop_conditions") or {})

    events = list(tool_events or [])
    ok_events = [e for e in events if str(e.get("status") or "").lower() in {"ok", "recovered", "selected"}]
    tool_calls_this_turn = len([e for e in events if str(e.get("tool") or "").strip() and str(e.get("tool") or "") != "model.router"])
    out["tool_call_count"] = int(out.get("tool_call_count") or 0) + tool_calls_this_turn
    out["cycle_count"] = int(out.get("cycle_count") or 0) + 1

    text = str(assistant_text or "").lower()
    progress = bool(ok_events) or bool(re.search(r"\b(done|completed|implemented|verified|finished|resolved)\b", text))
    if progress:
        out["no_progress_turns"] = 0
    else:
        out["no_progress_turns"] = int(out.get("no_progress_turns") or 0) + 1

    max_tools = max(1, int(stop.get("max_tool_calls") or 4))
    max_no_progress = max(1, int(stop.get("max_no_progress_turns") or 2))
    max_cycles = max(2, int(stop.get("max_cycles") or 6))

    if int(out.get("tool_call_count") or 0) >= max_tools:
        out["phase"] = "finalize"
        out["stop_reason"] = "max_tool_calls_reached"
    elif int(out.get("no_progress_turns") or 0) >= max_no_progress:
        out["phase"] = "finalize"
        out["stop_reason"] = "no_progress_guard"
    elif int(out.get("cycle_count") or 0) >= max_cycles:
        out["phase"] = "finalize"
        out["stop_reason"] = "max_cycles_reached"
    else:
        if phase == "plan":
            out["phase"] = "act"
        elif phase == "act":
            if progress:
                out["phase"] = "verify"
        elif phase == "verify":
            if progress:
                out["phase"] = "finalize"
        elif phase == "finalize":
            out["phase"] = "finalize"

    out["updated_at"] = _now_iso()
    return out


def render_plan_block(state: Dict[str, Any], *, max_items: int = 4) -> str:
    s = dict(state or {})
    phase = str(s.get("phase") or "plan")
    objective = _safe(s.get("objective"), max_len=180)
    steps = [_safe(x, max_len=150) for x in list(s.get("steps") or []) if str(x).strip()][:max_items]
    checks = [_safe(x, max_len=150) for x in list(s.get("checks") or []) if str(x).strip()][:max_items]
    stop = dict(s.get("stop_conditions") or {})

    lines = [
        "## Planner/Executor State",
        f"- phase: {phase}",
        f"- objective: {objective or '(unspecified)'}",
        f"- tool_call_count: {int(s.get('tool_call_count') or 0)}",
        f"- no_progress_turns: {int(s.get('no_progress_turns') or 0)}",
        f"- stop_limits: max_tools={int(stop.get('max_tool_calls') or 4)}, max_no_progress={int(stop.get('max_no_progress_turns') or 2)}, max_cycles={int(stop.get('max_cycles') or 6)}",
        "- instruction: execute only the minimum next action for current phase, then verify before continuing",
    ]

    stop_reason = _safe(s.get("stop_reason"), max_len=120)
    if stop_reason:
        lines.append(f"- stop_reason: {stop_reason}")

    if steps:
        lines.append("- next_steps:")
        for row in steps:
            lines.append(f"  - {row}")

    if checks:
        lines.append("- verification_checks:")
        for row in checks:
            lines.append(f"  - {row}")

    return "\n".join(lines)
