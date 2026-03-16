from __future__ import annotations

from config import toolboxsettings as tbs
from runtime.errors import PolicyError
from ops import OpsControlPlane

UNTRUSTED = "UNTRUSTED"
EXECUTION_BOUNDARY = {"verify", "execute", "install", "external_bulk", "run"}


def _assert_mode() -> None:
    tbs.assert_mode_safety()


def _record_policy(decision: str, reason: str, payload: dict) -> None:
    try:
        OpsControlPlane().record_policy_decision(
            surface="runtime.policy",
            decision=decision,
            reason=reason,
            payload=dict(payload or {}),
        )
    except Exception:
        pass


def enforce_policy(payload: dict) -> None:
    _assert_mode()
    trust = str(payload.get("trust", "")).strip().upper()
    action = str(payload.get("action", "")).strip().lower()
    if trust == UNTRUSTED and action in EXECUTION_BOUNDARY:
        _record_policy("blocked", "untrusted_execution_boundary", payload)
        raise PolicyError("UNTRUSTED payload cannot cross execution boundary")
    if tbs.normalized_mode() == tbs.MODE_SAFE and action in EXECUTION_BOUNDARY:
        _record_policy("blocked", "safe_mode_execution_boundary", payload)
        raise PolicyError("SAFE mode denies all execution boundary actions")
    if tbs.normalized_mode() != tbs.MODE_SYSTEM_AGENT and payload.get("system_wide"):
        _record_policy("blocked", "system_wide_requires_system_agent", payload)
        raise PolicyError("System-wide actions require system_agent mode")
    _record_policy("allowed", "policy_pass", payload)
