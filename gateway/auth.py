from __future__ import annotations

from typing import Any, Iterable


EXECUTION_ACTIONS = {"execute", "install", "system"}
LOCAL_SURFACES = {"gui", "desktop", "control_room", "coding_studio"}
SERVICE_SURFACES = {"telegram", "heartbeat", "automation", "workflow"}


def normalize_scopes(scopes: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for value in scopes or []:
        item = str(value or "").strip().lower()
        if item and item not in out:
            out.append(item)
    return out


def build_auth_context(
    *,
    surface: str,
    auth_mode: str = "local",
    pairing_record: dict[str, Any] | None = None,
    granted_scopes: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    surface_key = str(surface or "").strip().lower() or "unknown"
    auth_key = str(auth_mode or "").strip().lower() or "local"
    meta = dict(metadata or {})
    scopes = set(normalize_scopes(granted_scopes))
    if pairing_record:
        scopes.update(normalize_scopes(pairing_record.get("scopes") or []))

    trust_level = "untrusted_remote"
    allowed = {"pair"}

    if surface_key in LOCAL_SURFACES and auth_key in {"local", "desktop_local", "loopback"}:
        trust_level = "trusted_local"
        allowed = {"observe", "prompt", "deliver", "control", "pair"}
    elif surface_key in SERVICE_SURFACES and auth_key in {"service", "local", "loopback"}:
        trust_level = "trusted_service"
        allowed = {"observe", "prompt", "deliver"}
    elif pairing_record or auth_key in {"paired", "pairing"}:
        trust_level = "paired_remote"
        allowed = {"observe", "prompt", "deliver"}
    elif auth_key in {"observer", "view_only"}:
        trust_level = "observer"
        allowed = {"observe"}

    for scope in scopes:
        if scope in EXECUTION_ACTIONS:
            if surface_key == "node" and trust_level == "paired_remote":
                allowed.add(scope)
            continue
        if scope not in EXECUTION_ACTIONS:
            allowed.add(scope)

    allow_local_execution = bool(meta.get("allow_local_execution")) and trust_level == "trusted_local"
    if allow_local_execution:
        allowed.update({"execute", "install"})

    remote_safe = not any(action in EXECUTION_ACTIONS for action in allowed)
    return {
        "surface": surface_key,
        "auth_mode": auth_key,
        "trust_level": trust_level,
        "allowed_actions": sorted(allowed),
        "remote_safe": remote_safe,
        "paired": bool(pairing_record or auth_key in {"paired", "pairing"}),
    }


def authorize_action(context: dict[str, Any] | None, action: str) -> dict[str, Any]:
    ctx = dict(context or {})
    action_key = str(action or "").strip().lower()
    allowed = set(normalize_scopes(ctx.get("allowed_actions") or []))
    remote_safe = bool(ctx.get("remote_safe", True))
    trust_level = str(ctx.get("trust_level") or "unknown")

    if action_key in EXECUTION_ACTIONS and remote_safe:
        return {
            "allowed": False,
            "action": action_key,
            "trust_level": trust_level,
            "reason": "remote_safe_boundary",
        }
    if action_key not in allowed:
        return {
            "allowed": False,
            "action": action_key,
            "trust_level": trust_level,
            "reason": "scope_missing",
        }
    return {
        "allowed": True,
        "action": action_key,
        "trust_level": trust_level,
        "reason": "allowed",
    }
