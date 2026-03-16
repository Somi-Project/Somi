from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from workshop.toolbox.registry import ToolRegistry

from .backup_verifier import verify_recent_backups
from .control_plane import OpsControlPlane
from .repair import apply_safe_repairs


def _severity_rank(value: str) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(str(value or "").upper(), 1)


def _issue(severity: str, title: str, detail: Any, repair: str) -> dict[str, Any]:
    return {
        "severity": str(severity or "LOW").upper(),
        "title": str(title or ""),
        "detail": detail,
        "repair": str(repair or ""),
    }


def run_somi_doctor(root_dir: str | Path = ".", *, apply_repairs: bool = False) -> dict[str, Any]:
    root = Path(root_dir)
    applied_repairs = apply_safe_repairs(root) if apply_repairs else []

    registry = ToolRegistry(path=str(root / "workshop" / "tools" / "registry.json"))
    tools = registry.list_tools(include_disabled=True)
    unavailable = []
    for tool in tools:
        availability = registry.availability(tool)
        if not bool(availability.get("ok", False)):
            unavailable.append({"name": str(tool.get("name") or ""), "issues": list(availability.get("issues") or [])})

    ops = OpsControlPlane(root_dir=root / "sessions" / "ops")
    ops_snapshot = ops.snapshot(event_limit=12, metric_limit=24)
    backup_report = verify_recent_backups(root / "backups", limit=5)

    directories = {
        "backups": (root / "backups").exists(),
        "sessions": (root / "sessions").exists(),
        "database": (root / "database").exists(),
        "docs_architecture": (root / "docs" / "architecture").exists(),
        "venv": (root / ".venv").exists(),
    }

    issues: list[dict[str, Any]] = []
    missing_dirs = sorted([name for name, ok in directories.items() if not ok and name != "venv"])
    if missing_dirs:
        issues.append(
            _issue(
                "HIGH",
                "Core runtime directories are missing",
                {"missing": missing_dirs},
                "Run `python somi.py doctor --apply-safe-repairs` to recreate the baseline directories.",
            )
        )
    if not directories["venv"]:
        issues.append(
            _issue(
                "MEDIUM",
                "Project virtual environment is missing",
                {"path": str(root / ".venv")},
                "Create the `.venv` before shipping so the setup path stays predictable.",
            )
        )
    if int(backup_report.get("verified_count") or 0) <= 0:
        issues.append(
            _issue(
                "HIGH",
                "No recent verified backups were found",
                backup_report,
                "Create a fresh framework backup before making more changes or preparing a release.",
            )
        )
    if unavailable:
        issues.append(
            _issue(
                "MEDIUM",
                "Some registered tools are unavailable",
                {"count": len(unavailable), "tools": unavailable[:10]},
                "Repair missing tool paths, modules, or executables before relying on those capabilities.",
            )
        )

    repair_suggestions = [issue["repair"] for issue in issues if str(issue.get("repair") or "").strip()]
    highest = max((_severity_rank(issue.get("severity", "LOW")) for issue in issues), default=0)

    return {
        "ok": highest < _severity_rank("HIGH"),
        "root_dir": str(root),
        "python_executable": sys.executable,
        "directories": directories,
        "tools": {
            "total": len(tools),
            "unavailable_count": len(unavailable),
            "unavailable": unavailable[:10],
        },
        "ops": {
            "active_profile": dict(ops_snapshot.get("active_profile") or {}).get("profile_id", ""),
            "config_revision_count": int(ops_snapshot.get("config_revision_count", 0) or 0),
            "policy_decision_counts": dict(ops_snapshot.get("policy_decision_counts") or {}),
        },
        "backups": backup_report,
        "issues": issues,
        "repair_suggestions": repair_suggestions,
        "applied_repairs": applied_repairs,
    }


def format_somi_doctor(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Doctor]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- root_dir: {report.get('root_dir', '')}",
        f"- python: {report.get('python_executable', '')}",
        "",
        "Directories:",
    ]
    for key, ok in dict(report.get("directories") or {}).items():
        lines.append(f"- {key}: {'present' if ok else 'missing'}")
    tool_info = dict(report.get("tools") or {})
    lines.extend(
        [
            "",
            "Tools:",
            f"- total: {tool_info.get('total', 0)}",
            f"- unavailable: {tool_info.get('unavailable_count', 0)}",
            "",
            "Backups:",
            f"- verified_recent: {dict(report.get('backups') or {}).get('verified_count', 0)}",
            f"- recent_seen: {dict(report.get('backups') or {}).get('recent_count', 0)}",
            "",
            "Issues:",
        ]
    )
    issues = list(report.get("issues") or [])
    if not issues:
        lines.append("- none")
    for issue in issues:
        lines.append(f"- [{issue.get('severity')}] {issue.get('title')}")
    repairs = list(report.get("repair_suggestions") or [])
    lines.append("")
    lines.append("Repairs:")
    if not repairs:
        lines.append("- none")
    else:
        for repair in repairs:
            lines.append(f"- {repair}")
    return "\n".join(lines)


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)
