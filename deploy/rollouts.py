from __future__ import annotations

import shutil
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

from .profiles import RuntimeProfile, get_profile


def _memory_gb() -> float | None:
    if psutil is None:
        return None
    try:
        return round(float(psutil.virtual_memory().total) / float(1024**3), 2)
    except Exception:
        return None


def evaluate_rollout(profile: RuntimeProfile | dict[str, Any] | str) -> dict[str, Any]:
    resolved: RuntimeProfile | None
    if isinstance(profile, RuntimeProfile):
        resolved = profile
    elif isinstance(profile, dict):
        item = dict(profile)
        resolved = RuntimeProfile(
            profile_id=str(item.get("profile_id") or item.get("id") or "profile"),
            display_name=str(item.get("display_name") or item.get("profile_id") or "Profile"),
            description=str(item.get("description") or ""),
            allowed_backends=tuple(item.get("allowed_backends") or []),
            default_model_profile=str(item.get("default_model_profile") or "balanced"),
            max_risk_tier=str(item.get("max_risk_tier") or "LOW"),
            delivery_channels=tuple(item.get("delivery_channels") or []),
            rollout_gates=dict(item.get("rollout_gates") or {}),
            metadata=dict(item.get("metadata") or {}),
        )
    else:
        resolved = get_profile(str(profile or ""))

    if resolved is None:
        return {"ok": False, "issues": ["unknown_profile"], "checks": []}

    gates = dict(resolved.rollout_gates or {})
    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    for executable in list(gates.get("required_executables") or []):
        ok = shutil.which(str(executable)) is not None
        checks.append({"name": f"executable:{executable}", "ok": ok})
        if not ok:
            issues.append(f"missing_executable:{executable}")

    for executable in list(gates.get("optional_executables") or []):
        ok = shutil.which(str(executable)) is not None
        checks.append({"name": f"optional_executable:{executable}", "ok": ok})

    min_memory_gb = gates.get("min_memory_gb")
    if min_memory_gb is not None:
        available = _memory_gb()
        ok = available is None or float(available) >= float(min_memory_gb)
        checks.append({"name": "memory_gb", "ok": ok, "required": float(min_memory_gb), "available": available})
        if not ok:
            issues.append(f"insufficient_memory:{available}")

    return {
        "ok": not issues,
        "issues": issues,
        "checks": checks,
        "profile": resolved.to_dict(),
    }
