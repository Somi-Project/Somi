from __future__ import annotations

"""Extracted Agent methods from agents.py (coding_methods.py)."""


def _handle_coding_command_or_intent(
    self,
    prompt: str,
    *,
    active_user_id: str,
    thread_id: str,
    turn_trace: Any = None,
    source: str = "chat",
) -> Dict[str, Any]:
    service = getattr(self, "coding_sessions", None)
    if service is None:
        return {"handled": False}

    trigger = service.detect_trigger(prompt)
    if not bool(trigger.get("requested", False)):
        return {"handled": False}

    objective = str(trigger.get("objective") or prompt or "").strip()
    metadata = {
        "trigger": str(trigger.get("command") or ""),
        "thread_id": str(thread_id or "general"),
        "turn_id": getattr(turn_trace, "turn_id", None),
        "entrypoint": str(source or "chat"),
        "force_open": bool(trigger.get("force_open", False)),
    }

    try:
        snapshot = service.open_session(
            user_id=active_user_id,
            source=source,
            objective=objective,
            metadata=metadata,
            resume_active=True,
        )
    except Exception as exc:
        return {
            "handled": True,
            "response": f"I tried to open coding mode but hit an error: {type(exc).__name__}: {exc}",
            "turn_status": "failed",
            "event_type": "coding_session_failed",
            "event_name": "coding_session_failed",
            "event_payload": {
                "user_id": str(active_user_id or "default_user"),
                "thread_id": str(thread_id or "general"),
                "error": f"{type(exc).__name__}: {exc}",
            },
            "tool_event": {"tool": "coding.session", "status": "failed", "detail": type(exc).__name__},
            "metadata": {"coding_mode": False},
        }

    workspace = dict(snapshot.get("workspace") or {})
    recent_files = [str(x) for x in list(workspace.get("recent_files") or []) if str(x).strip()]
    lines = [str(snapshot.get("welcome_text") or "").strip()]
    if recent_files:
        lines.append("Recent files:")
        for item in recent_files[:5]:
            lines.append(f"- {item}")
    skill_hint = dict(snapshot.get("metadata") or {}).get("skill_expansion") or {}
    if isinstance(skill_hint, dict) and str(skill_hint.get("capability") or "").strip() and bool(skill_hint.get("proposal_ready", True)):
        lines.append(
            f"I can scaffold a dedicated skill draft for {skill_hint['capability']} if this task needs it."
        )
    lines.append(f"Session ID: {snapshot.get('session_id') or '--'}")
    lines.append("You can keep working here in chat while this coding session stays attached to the workspace.")

    return {
        "handled": True,
        "response": "\n".join(line for line in lines if line).strip(),
        "turn_status": "completed",
        "event_type": "coding_session_opened",
        "event_name": "coding_session_opened",
        "event_payload": {
            "session_id": str(snapshot.get("session_id") or ""),
            "workspace_id": str(workspace.get("workspace_id") or ""),
            "workspace_root": str(workspace.get("root_path") or ""),
            "trigger": str(trigger.get("command") or ""),
            "user_id": str(active_user_id or "default_user"),
            "thread_id": str(thread_id or "general"),
            "source": str(source or "chat"),
        },
        "tool_event": {
            "tool": "coding.session",
            "status": "ok",
            "detail": str(snapshot.get("session_id") or "opened"),
        },
        "metadata": {
            "coding_mode": True,
            "coding_session_id": str(snapshot.get("session_id") or ""),
            "coding_workspace_root": str(workspace.get("root_path") or ""),
        },
    }
