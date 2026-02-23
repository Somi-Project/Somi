from __future__ import annotations

from runtime.errors import PolicyError

UNTRUSTED = "UNTRUSTED"


def enforce_policy(payload: dict) -> None:
    trust = str(payload.get("trust", "")).strip().upper()
    action = str(payload.get("action", "")).strip().lower()
    if trust == UNTRUSTED and action in {"execute", "install", "run"}:
        raise PolicyError("UNTRUSTED payload cannot execute boundary actions")
