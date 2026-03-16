from __future__ import annotations

"""Extracted Agent methods from agents.py (subagent_methods.py)."""

from typing import Any, Dict, List, Optional

from executive.strategic.delegation import select_subagent_profile
from workshop.toolbox.agent_core.delegation import parse_delegation_command, render_delegation_help


def list_subagent_profiles(self) -> List[Dict[str, Any]]:
    registry = getattr(self, "subagent_registry", None)
    if registry is None:
        return []
    try:
        return list(registry.list_profiles())
    except Exception:
        return []


def get_subagent_status(self, run_id: str, *, user_id: str = "default_user") -> Optional[Dict[str, Any]]:
    executor = getattr(self, "subagent_executor", None)
    if executor is not None:
        try:
            snapshot = executor.get_status(run_id)
            if snapshot is not None and str(snapshot.get("user_id") or "") == str(user_id or self.user_id):
                return snapshot
        except Exception:
            pass
    store = getattr(self, "subagent_status_store", None)
    if store is None:
        return None
    try:
        snapshot = store.load_snapshot(run_id)
    except Exception:
        return None
    if not isinstance(snapshot, dict):
        return None
    if str(snapshot.get("user_id") or "") != str(user_id or self.user_id):
        return None
    return snapshot


def delegate_subagent(
    self,
    objective: str,
    *,
    user_id: str = "default_user",
    thread_id: str = "general",
    preferred_profile: str = "",
    allowed_tools: Optional[List[str]] = None,
    max_turns: Optional[int] = None,
    backend: str = "",
    timeout_seconds: Optional[int] = None,
    budget_tokens: Optional[int] = None,
    artifact_refs: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    background: bool = True,
    parent_turn_id: Optional[int] = None,
    parent_session_id: str = "",
) -> Dict[str, Any]:
    registry = getattr(self, "subagent_registry", None)
    executor = getattr(self, "subagent_executor", None)
    if registry is None or executor is None:
        raise RuntimeError("Subagent runtime is not initialized")

    meta = dict(metadata or {})
    profile_key = select_subagent_profile(
        objective,
        preferred=str(preferred_profile or ""),
        metadata=meta,
        available_profiles=getattr(registry, "keys", lambda: [])(),
    )
    spec = registry.build_spec(
        profile_key=profile_key,
        objective=objective,
        user_id=str(user_id or self.user_id),
        thread_id=str(thread_id or "general"),
        allowed_tools=list(allowed_tools or []),
        max_turns=max_turns,
        backend=str(backend or ""),
        timeout_seconds=timeout_seconds,
        budget_tokens=budget_tokens,
        parent_turn_id=parent_turn_id,
        parent_session_id=str(parent_session_id or ""),
        artifact_refs=list(artifact_refs or []),
        metadata=meta,
    )
    if background:
        return executor.submit(spec)
    return executor.run(spec)


def _format_subagent_snapshot(snapshot: Dict[str, Any], *, verbose: bool = False) -> str:
    status = str(snapshot.get("status") or "unknown")
    run_id = str(snapshot.get("run_id") or "")
    profile_name = str(snapshot.get("profile_name") or snapshot.get("profile_key") or "subagent")
    objective = str(snapshot.get("objective") or "")
    lines = [
        f"{profile_name} [{run_id}]",
        f"status: {status}",
        f"objective: {objective}",
    ]
    summary = str(snapshot.get("summary") or "").strip()
    if summary:
        lines.append("")
        lines.append(summary)
    if verbose:
        tool_events = list(snapshot.get("tool_events") or [])
        if tool_events:
            lines.append("")
            lines.append("tool events:")
            for event in tool_events[:5]:
                lines.append(f"- {event.get('tool')}: {event.get('status')} ({event.get('detail')})")
        artifact_refs = list(snapshot.get("artifact_refs") or [])
        if artifact_refs:
            lines.append("")
            lines.append("artifacts: " + ", ".join(artifact_refs[:5]))
    return "\n".join(lines).strip()


def _handle_subagent_command(
    self,
    prompt: str,
    *,
    active_user_id: str,
    thread_id: str,
    turn_trace: Any = None,
) -> Dict[str, Any]:
    profiles = self.list_subagent_profiles()
    parsed = parse_delegation_command(prompt, known_profiles=[str(row.get("key") or "") for row in profiles])
    if not bool(parsed.get("handled")):
        return {"handled": False}

    action = str(parsed.get("action") or "help")
    if action == "help":
        return {
            "handled": True,
            "response": render_delegation_help(profiles),
            "turn_status": "completed",
            "tool_event": {"tool": "subagent.delegate", "status": "ok", "detail": "help"},
            "event_type": "subagent_help",
            "event_name": "subagent_help",
        }

    if action == "list":
        lines = ["Available subagent profiles:"]
        for profile in profiles:
            lines.append(
                f"- {profile.get('key')}: {profile.get('display_name')} | tools={', '.join(list(profile.get('default_allowed_tools') or [])[:4])}"
            )
        return {
            "handled": True,
            "response": "\n".join(lines),
            "turn_status": "completed",
            "tool_event": {"tool": "subagent.delegate", "status": "ok", "detail": "list"},
            "event_type": "subagent_listed",
            "event_name": "subagent_listed",
        }

    if action == "active":
        executor = getattr(self, "subagent_executor", None)
        rows = []
        if executor is not None:
            try:
                rows = executor.list_snapshots(user_id=active_user_id, thread_id=thread_id, statuses=["queued", "running"], limit=8)
            except Exception:
                rows = []
        if not rows:
            response = "No queued or running subagents for this thread."
        else:
            parts = ["Active subagents:"]
            for row in rows:
                parts.append(
                    f"- {row.get('profile_name') or row.get('profile_key')} [{row.get('run_id')}]: {row.get('status')} | {row.get('objective')}"
                )
            response = "\n".join(parts)
        return {
            "handled": True,
            "response": response,
            "turn_status": "completed",
            "tool_event": {"tool": "subagent.delegate", "status": "ok", "detail": "active"},
            "event_type": "subagent_active_listed",
            "event_name": "subagent_active_listed",
        }

    if action == "status":
        run_id = str(parsed.get("run_id") or "").strip()
        snapshot = self.get_subagent_status(run_id, user_id=active_user_id)
        if snapshot is None:
            return {
                "handled": True,
                "response": f"I couldn't find a subagent run with id '{run_id}' for this user.",
                "turn_status": "blocked",
                "tool_event": {"tool": "subagent.status", "status": "failed", "detail": "not_found"},
                "event_type": "subagent_status_missing",
                "event_name": "subagent_status_missing",
            }
        return {
            "handled": True,
            "response": _format_subagent_snapshot(snapshot, verbose=True),
            "turn_status": "completed",
            "tool_event": {"tool": "subagent.status", "status": str(snapshot.get("status") or "ok"), "detail": run_id},
            "event_type": "subagent_status_read",
            "event_name": "subagent_status_read",
            "event_payload": {
                "run_id": str(snapshot.get("run_id") or ""),
                "status": str(snapshot.get("status") or ""),
                "profile_key": str(snapshot.get("profile_key") or ""),
            },
        }

    objective = str(parsed.get("objective") or "").strip()
    if not objective:
        return {
            "handled": True,
            "response": render_delegation_help(profiles),
            "turn_status": "blocked",
            "tool_event": {"tool": "subagent.delegate", "status": "failed", "detail": "missing_objective"},
            "event_type": "subagent_delegate_failed",
            "event_name": "subagent_delegate_failed",
        }

    snapshot = self.delegate_subagent(
        objective,
        user_id=active_user_id,
        thread_id=thread_id,
        preferred_profile=str(parsed.get("preferred_profile") or ""),
        metadata={"source": "chat_command"},
        background=True,
        parent_turn_id=getattr(turn_trace, "turn_id", None),
        parent_session_id=str(getattr(turn_trace, "session_id", "") or ""),
    )
    response = (
        f"Delegated to {snapshot.get('profile_name') or snapshot.get('profile_key')} as `{snapshot.get('run_id')}`.\n"
        f"Status: {snapshot.get('status')}.\n"
        f"Use `/delegate status {snapshot.get('run_id')}` to inspect the child run."
    )
    return {
        "handled": True,
        "response": response,
        "turn_status": "completed",
        "tool_event": {"tool": "subagent.delegate", "status": str(snapshot.get("status") or "queued"), "detail": str(snapshot.get("profile_key") or "")},
        "event_type": "subagent_delegated",
        "event_name": str(snapshot.get("profile_key") or "subagent"),
        "event_payload": {
            "run_id": str(snapshot.get("run_id") or ""),
            "profile_key": str(snapshot.get("profile_key") or ""),
            "status": str(snapshot.get("status") or ""),
            "child_thread_id": str(snapshot.get("child_thread_id") or ""),
        },
        "metadata": {
            "subagent_run_id": str(snapshot.get("run_id") or ""),
            "subagent_profile": str(snapshot.get("profile_key") or ""),
        },
    }
