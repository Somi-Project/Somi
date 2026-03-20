from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from workshop.toolbox.registry import ToolRegistry

from .backup_verifier import verify_recent_backups
from .context_budget import run_context_budget_status
from .artifact_hygiene import run_artifact_hygiene
from .control_plane import OpsControlPlane
from .docs_integrity import run_docs_integrity
from .offline_resilience import run_offline_resilience
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
    backup_roots = list(backup_report.get("roots") or [])
    docs_integrity = run_docs_integrity(root)
    artifact_hygiene = run_artifact_hygiene(root)
    offline_resilience = run_offline_resilience(root)
    context_budget = run_context_budget_status(root)

    directories = {
        "backups": bool(backup_roots),
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
    if not bool(docs_integrity.get("ok")):
        issues.append(
            _issue(
                "MEDIUM",
                "Contributor documentation has missing or stale checkpoints",
                docs_integrity,
                "Repair the contributor-map/readme coverage before calling the framework release-ready for newcomers.",
            )
        )
    if not bool(artifact_hygiene.get("ok")):
        issues.append(
            _issue(
                "LOW",
                "Generated artifacts are drifting past the current hygiene budgets",
                artifact_hygiene,
                "Archive or trim older generated reports before the next long upgrade or benchmark pass.",
            )
        )
    if not bool(offline_resilience.get("ok")):
        issues.append(
            _issue(
                "LOW",
                "Offline resilience posture is still too thin for degraded-network operation",
                offline_resilience,
                "Seed the missing local packs and cached evidence so Somi stays useful when the network is unavailable.",
            )
        )
    if str(context_budget.get("status") or "") == "warn":
        issues.append(
            _issue(
                "LOW",
                "Long-running conversation context is under pressure",
                context_budget,
                "Resume or compact the flagged threads so Somi preserves constraints and open loops before context quality drops.",
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
            "available_count": max(0, len(tools) - len(unavailable)),
            "unavailable_count": len(unavailable),
            "unavailable": unavailable[:10],
        },
        "ops": {
            "active_profile": dict(ops_snapshot.get("active_profile") or {}).get("profile_id", ""),
            "config_revision_count": int(ops_snapshot.get("config_revision_count", 0) or 0),
            "policy_decision_counts": dict(ops_snapshot.get("policy_decision_counts") or {}),
        },
        "backups": backup_report,
        "backup_roots": backup_roots,
        "docs_integrity": docs_integrity,
        "artifact_hygiene": artifact_hygiene,
        "offline_resilience": offline_resilience,
        "context_budget": context_budget,
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
            f"- roots: {', '.join(list(report.get('backup_roots') or [])) or '--'}",
            f"- verified_recent: {dict(report.get('backups') or {}).get('verified_count', 0)}",
            f"- recent_seen: {dict(report.get('backups') or {}).get('recent_count', 0)}",
            "",
            "Docs:",
            f"- ok: {bool(dict(report.get('docs_integrity') or {}).get('ok', False))}",
            f"- broken_links: {len(list(dict(report.get('docs_integrity') or {}).get('broken_links') or []))}",
            "",
            "Artifacts:",
            f"- ok: {bool(dict(report.get('artifact_hygiene') or {}).get('ok', False))}",
            f"- warnings: {len(list(dict(report.get('artifact_hygiene') or {}).get('warnings') or []))}",
            "",
            "Offline:",
            f"- ok: {bool(dict(report.get('offline_resilience') or {}).get('ok', False))}",
            f"- readiness: {dict(report.get('offline_resilience') or {}).get('readiness', 'blocked')}",
            f"- fallback_order: {', '.join(list(dict(report.get('offline_resilience') or {}).get('fallback_order') or [])) or '--'}",
            "",
            "Context:",
            f"- status: {dict(report.get('context_budget') or {}).get('status', 'idle')}",
            f"- pressure_threads: {dict(report.get('context_budget') or {}).get('pressure_count', 0)}",
            f"- compacted_sessions: {dict(report.get('context_budget') or {}).get('compacted_session_count', 0)}",
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
