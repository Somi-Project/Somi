from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from runtime.ticketing import ExecutionTicket


@dataclass
class RiskReport:
    tier: str
    reasons: list[str] = field(default_factory=list)
    potential_outcomes: list[str] = field(default_factory=list)
    required_confirm: str = "single"


_DESTRUCTIVE = [
    "rm",
    "del",
    "rmdir",
    "git clean -fdx",
    "git reset --hard",
    "curl|sh",
    "powershell",
    "iex",
]
_INSTALL_PATTERNS = [("pip", "install"), ("npm", "install")]


def assess(
    ticket: ExecutionTicket, targetset: dict | None = None, settings=None
) -> RiskReport:
    tier = "LOW"
    reasons: list[str] = []
    outcomes: list[str] = []

    flat_cmds = [" ".join(c).lower() for c in ticket.commands]
    if any(any(p in c for p in _DESTRUCTIVE) for c in flat_cmds):
        tier = "CRITICAL"
        reasons.append("destructive command pattern detected")
        outcomes.append("data loss")

    if any(
        any(c[:2] == list(p) for p in _INSTALL_PATTERNS)
        for c in ticket.commands
        if len(c) >= 2
    ):
        tier = "HIGH" if tier in {"LOW", "MEDIUM"} else tier
        reasons.append("dependency install requested")
        outcomes.append("environment changes")

    if ticket.allow_network:
        tier = "HIGH" if tier in {"LOW", "MEDIUM"} else tier
        reasons.append("network enabled")
    if ticket.allow_external_apps:
        tier = "HIGH" if tier in {"LOW", "MEDIUM"} else tier
        reasons.append("external app access")
    if ticket.allow_delete:
        tier = "CRITICAL"
        reasons.append("delete actions enabled")
    if ticket.allow_system_wide:
        tier = "CRITICAL"
        reasons.append("system-wide actions enabled")

    protected = (
        [Path(p).expanduser() for p in getattr(settings, "PROTECTED_PATHS", [])]
        if settings
        else []
    )
    for p in ticket.paths_rw:
        rp = Path(p).expanduser()
        if any(str(rp).startswith(str(prot)) for prot in protected):
            tier = "CRITICAL"
            reasons.append(f"touches protected path: {p}")

    if targetset and targetset.get("estimated_count", 0) > 0:
        tier = "HIGH" if tier in {"LOW", "MEDIUM"} else tier
        reasons.append("bulk operation")

    required = "single"
    if tier == "MEDIUM":
        required = "double"
    if tier in {"HIGH", "CRITICAL"}:
        required = "typed"

    return RiskReport(
        tier=tier,
        reasons=sorted(set(reasons)),
        potential_outcomes=sorted(set(outcomes)),
        required_confirm=required,
    )
