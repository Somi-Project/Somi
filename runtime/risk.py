from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from runtime.ticketing import ExecutionTicket


@dataclass
class RiskReport:
    tier: str
    reasons: list[str] = field(default_factory=list)
    potential_outcomes: list[str] = field(default_factory=list)
    required_confirm: str = "single_click"


def _raise_tier(current: str, target: str) -> str:
    order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    return order[max(order.index(current), order.index(target))]


def assess(ticket: ExecutionTicket, targetset: dict | None = None, settings=None) -> RiskReport:
    tier = "LOW"
    reasons: list[str] = []
    outcomes: list[str] = []
    flat = "\n".join(" ".join(c).lower() for c in ticket.commands)

    if any(x in flat for x in [" rm ", "del ", "rmdir", "git clean -fd", "--delete"]):
        tier = _raise_tier(tier, "CRITICAL")
        reasons.append("delete operations detected")
        outcomes.append("potential irreversible data loss")
    if any(x in flat for x in ["/etc", "/usr", "/var", "c:/windows", "c:/users"]):
        tier = _raise_tier(tier, "CRITICAL")
        reasons.append("system directory modification pattern detected")
    if ticket.allow_delete:
        tier = _raise_tier(tier, "CRITICAL")
        reasons.append("delete capability enabled")
        outcomes.append("potential irreversible data loss")
    if ticket.allow_network or any(x in flat for x in ["curl ", "wget ", "http://", "https://"]):
        tier = _raise_tier(tier, "HIGH")
        reasons.append("network access requested")
    if any(x in flat for x in ["pip install", "npm install", "apt install", "brew install"]):
        tier = _raise_tier(tier, "HIGH")
        reasons.append("package install operation detected")
        outcomes.append("environment changes")
    if targetset and int(targetset.get("estimated_count", 0)) > 100:
        tier = _raise_tier(tier, "HIGH")
        reasons.append("large bulk operation")
    if ticket.allow_system_wide:
        tier = _raise_tier(tier, "CRITICAL")
        reasons.append("system-wide capability enabled")

    protected = [Path(p).expanduser() for p in getattr(settings, "PROTECTED_PATHS", [])] if settings else []
    for p in ticket.paths_rw:
        rp = Path(p).expanduser()
        if any(str(rp).startswith(str(prot)) for prot in protected):
            tier = _raise_tier(tier, "CRITICAL")
            reasons.append(f"protected path targeted: {p}")

    required = "single_click" if tier == "LOW" else "double_confirm" if tier == "MEDIUM" else "typed"
    return RiskReport(tier=tier, reasons=sorted(set(reasons)), potential_outcomes=sorted(set(outcomes)), required_confirm=required)
