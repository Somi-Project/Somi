from __future__ import annotations

from config import toolboxsettings as tbs
from runtime.errors import PolicyError

UNTRUSTED = "UNTRUSTED"
EXECUTION_BOUNDARY = {"verify", "execute", "install", "external_bulk", "run"}


def _assert_mode() -> None:
    tbs.assert_mode_safety()


def enforce_policy(payload: dict) -> None:
    _assert_mode()
    trust = str(payload.get("trust", "")).strip().upper()
    action = str(payload.get("action", "")).strip().lower()
    if trust == UNTRUSTED and action in EXECUTION_BOUNDARY:
        raise PolicyError("UNTRUSTED payload cannot cross execution boundary")
    if tbs.normalized_mode() == tbs.MODE_SAFE and action in EXECUTION_BOUNDARY:
        raise PolicyError("SAFE mode denies all execution boundary actions")
    if tbs.normalized_mode() != tbs.MODE_SYSTEM_AGENT and payload.get("system_wide"):
        raise PolicyError("System-wide actions require system_agent mode")
