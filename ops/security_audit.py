from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config import settings as app_settings
from config import toolboxsettings as tbs
from gateway import GatewayService
from runtime.runtime_secrets import resolve_runtime_secret, runtime_secret_status
from workshop.toolbox.registry import ToolRegistry

from .backup_verifier import verify_recent_backups


def _severity_rank(value: str) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(str(value or "").upper(), 1)


def _finding(severity: str, title: str, detail: Any, repair: str) -> dict[str, Any]:
    return {
        "severity": str(severity or "LOW").upper(),
        "title": str(title or ""),
        "detail": detail,
        "repair": str(repair or ""),
    }


def run_security_audit(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir)
    registry = ToolRegistry(path=str(root / "workshop" / "tools" / "registry.json"))
    gateway = GatewayService(root_dir=root / "sessions" / "gateway")
    backups = verify_recent_backups(root / "backups", limit=3)
    findings: list[dict[str, Any]] = []
    secret_status = runtime_secret_status(root_dir=root, create=True)

    for tool in registry.list_tools(include_disabled=True):
        policy = dict(tool.get("policy") or {})
        exposure = dict(tool.get("exposure") or {})
        availability = registry.availability(tool)
        risk_tier = str(policy.get("risk_tier") or "LOW").upper()
        read_only = bool(policy.get("read_only", False))
        requires_approval = bool(policy.get("requires_approval", False))
        mutates_state = bool(policy.get("mutates_state", not read_only))

        if mutates_state and not requires_approval:
            severity = "HIGH" if risk_tier in {"HIGH", "CRITICAL"} else "MEDIUM"
            findings.append(
                _finding(
                    severity,
                    f"Mutating tool without approval: {tool.get('name')}",
                    {
                        "risk_tier": risk_tier,
                        "channels": list(tool.get("channels") or []),
                        "toolsets": list(tool.get("toolsets") or []),
                    },
                    "Require approval for mutating tools unless there is a strong local-only reason not to.",
                )
            )

        if mutates_state and bool(exposure.get("automation", False)) and risk_tier in {"HIGH", "CRITICAL"}:
            findings.append(
                _finding(
                    "HIGH",
                    f"High-risk mutating tool exposed to automation: {tool.get('name')}",
                    {
                        "risk_tier": risk_tier,
                        "channels": list(tool.get("channels") or []),
                        "exposure": exposure,
                    },
                    "Limit automation exposure or lower the tool's blast radius before release.",
                )
            )

        if not bool(availability.get("ok", True)):
            findings.append(
                _finding(
                    "LOW",
                    f"Unavailable registered tool: {tool.get('name')}",
                    {"issues": list(availability.get("issues") or [])},
                    "Repair or unregister unavailable tools so users do not hit dead capability surfaces.",
                )
            )

    snapshot = gateway.snapshot(limit=16)
    for session in list(snapshot.get("sessions") or []):
        decision = gateway.authorize_action(str(session.get("session_id") or ""), "execute")
        if bool(decision.get("allowed", False)):
            findings.append(
                _finding(
                    "CRITICAL",
                    "Remote or external session can execute actions",
                    {
                        "session_id": str(session.get("session_id") or ""),
                        "surface": str(session.get("surface") or ""),
                        "trust_level": str(session.get("trust_level") or ""),
                    },
                    "Remove execution rights from non-local surfaces and re-check pairing rules.",
                )
            )

    audit_secret = resolve_runtime_secret("audit_hmac", root_dir=root, create=True)
    if not bool(audit_secret.get("present")):
        findings.append(
            _finding(
                "MEDIUM",
                "Audit HMAC secret is unset",
                {"env": "SOMI_AUDIT_SECRET", "setting": "AUDIT_HMAC_SECRET"},
                "Set an audit HMAC secret before enterprise release so audit trails are tamper-evident.",
            )
        )

    approval_secret = resolve_runtime_secret("approval", root_dir=root, create=True)
    if not bool(approval_secret.get("present")):
        findings.append(
            _finding(
                "MEDIUM",
                "Approval secret is using the built-in fallback",
                {"env": "SOMI_APPROVAL_SECRET"},
                "Set `SOMI_APPROVAL_SECRET` so approval tokens are not derived from the default fallback.",
            )
        )

    if tbs.normalized_mode() == tbs.MODE_SYSTEM_AGENT or bool(tbs.ENABLE_SYSTEM_AGENT_MODE):
        findings.append(
            _finding(
                "HIGH",
                "System agent mode is enabled",
                {
                    "mode": tbs.normalized_mode(),
                    "allow_external_apps": bool(tbs.ALLOW_EXTERNAL_APPS),
                    "allow_system_wide_actions": bool(tbs.ALLOW_SYSTEM_WIDE_ACTIONS),
                },
                "Disable system-agent mode for default builds unless you are preparing a tightly controlled admin profile.",
            )
        )

    if bool(tbs.ALLOW_EXTERNAL_APPS) or bool(tbs.ALLOW_SYSTEM_WIDE_ACTIONS) or bool(tbs.ALLOW_DELETE_ACTIONS):
        findings.append(
            _finding(
                "HIGH",
                "One or more broad toolbox permissions are enabled",
                {
                    "allow_external_apps": bool(tbs.ALLOW_EXTERNAL_APPS),
                    "allow_system_wide_actions": bool(tbs.ALLOW_SYSTEM_WIDE_ACTIONS),
                    "allow_delete_actions": bool(tbs.ALLOW_DELETE_ACTIONS),
                },
                "Keep broad mutation toggles disabled in the default release profile.",
            )
        )

    trust_doc = root / "docs" / "architecture" / "TRUST_BOUNDARIES.md"
    if not trust_doc.exists():
        findings.append(
            _finding(
                "LOW",
                "Trust-boundary documentation is missing",
                {"path": str(trust_doc)},
                "Add a trust-boundary document before shipping so operators understand local, service, and remote blast radius.",
            )
        )

    if int(backups.get("verified_count") or 0) <= 0:
        findings.append(
            _finding(
                "HIGH",
                "No recent verified backups were found",
                backups,
                "Create and verify a backup before more changes or release preparation.",
            )
        )

    severity_counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "LOW")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    highest = max((_severity_rank(finding.get("severity", "LOW")) for finding in findings), default=0)
    repairs = [finding["repair"] for finding in findings if str(finding.get("repair") or "").strip()]

    return {
        "ok": highest < _severity_rank("HIGH"),
        "root_dir": str(root),
        "summary": {
            "finding_count": len(findings),
            "severity_counts": severity_counts,
            "remote_session_count": len(list(snapshot.get("sessions") or [])),
        },
        "findings": findings,
        "repair_suggestions": repairs,
        "backups": backups,
        "backup_roots": list(backups.get("roots") or []),
        "runtime_secrets": secret_status,
    }


def format_security_audit(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Security Audit]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- findings: {dict(report.get('summary') or {}).get('finding_count', 0)}",
        f"- severity_counts: {dict(report.get('summary') or {}).get('severity_counts', {})}",
        "",
        "Findings:",
    ]
    findings = list(report.get("findings") or [])
    if not findings:
        lines.append("- none")
    else:
        for finding in findings:
            lines.append(f"- [{finding.get('severity')}] {finding.get('title')}")
    lines.append("")
    lines.append("Repairs:")
    repairs = list(report.get("repair_suggestions") or [])
    if not repairs:
        lines.append("- none")
    else:
        for repair in repairs:
            lines.append(f"- {repair}")
    return "\n".join(lines)


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)
