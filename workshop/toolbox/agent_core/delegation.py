from __future__ import annotations

from typing import Any, Iterable


def parse_delegation_command(text: str, *, known_profiles: Iterable[str] | None = None) -> dict[str, Any]:
    prompt = str(text or "").strip()
    if not prompt.lower().startswith("/delegate"):
        return {"handled": False}

    body = prompt[len("/delegate") :].strip()
    profiles = {str(x or "").strip().lower() for x in list(known_profiles or []) if str(x or "").strip()}

    if not body or body.lower() in {"help", "?"}:
        return {"handled": True, "action": "help"}
    if body.lower() == "list":
        return {"handled": True, "action": "list"}
    if body.lower() == "active":
        return {"handled": True, "action": "active"}
    if body.lower().startswith("status "):
        run_id = body.split(None, 1)[1].strip()
        return {"handled": True, "action": "status", "run_id": run_id}

    preferred_profile = ""
    objective = body
    if " -- " in body:
        head, tail = body.split(" -- ", 1)
        if head.strip().lower() in profiles:
            preferred_profile = head.strip().lower()
            objective = tail.strip()
    else:
        parts = body.split(None, 1)
        if parts and parts[0].strip().lower() in profiles:
            preferred_profile = parts[0].strip().lower()
            objective = parts[1].strip() if len(parts) > 1 else ""

    if not objective:
        return {"handled": True, "action": "help", "error": "objective_required"}

    return {
        "handled": True,
        "action": "run",
        "preferred_profile": preferred_profile,
        "objective": objective,
    }


def render_delegation_help(profiles: list[dict[str, Any]]) -> str:
    lines = [
        "Subagent delegation commands:",
        "- `/delegate list` shows the available specialist profiles.",
        "- `/delegate active` shows queued or running subagents for this thread.",
        "- `/delegate status <run_id>` shows the latest child status snapshot.",
        "- `/delegate research_scout -- investigate the latest local model benchmarks` starts a named profile.",
        "- `/delegate compare the latest Ollama GUI options` lets Somi auto-pick a profile.",
        "",
        "Available profiles:",
    ]
    for profile in list(profiles or []):
        lines.append(
            f"- `{profile.get('key')}`: {profile.get('display_name')} | tools={', '.join(list(profile.get('default_allowed_tools') or [])[:4])}"
        )
    return "\n".join(lines)
