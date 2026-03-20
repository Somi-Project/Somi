from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backup_verifier import verify_recent_backups
from .control_plane import OpsControlPlane
from .context_budget import run_context_budget_status
from .doctor import run_somi_doctor
from .observability import build_observability_digest
from .release_gate import list_release_reports, load_latest_release_report
from .security_audit import run_security_audit
from runtime.task_graph import load_task_graph
from runtime.task_resume import build_resume_ledger
from state import SessionEventStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return text.strip("-") or "snapshot"


def _support_dir(root_dir: str | Path) -> Path:
    path = Path(root_dir) / "sessions" / "support"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _render_support_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Somi Support Bundle",
        "",
        f"- Generated: {report.get('generated_at', '')}",
        f"- Root: {report.get('root_dir', '')}",
        f"- Status: {report.get('status', '')}",
        f"- Label: {report.get('label', '')}",
        "",
        "## Doctor",
        "",
        f"- ok: {dict(report.get('doctor') or {}).get('ok', False)}",
        f"- verified_backups: {dict(dict(report.get('doctor') or {}).get('backups') or {}).get('verified_count', 0)}",
        f"- repair_suggestions: {len(list(dict(report.get('doctor') or {}).get('repair_suggestions') or []))}",
        "",
        "## Security",
        "",
        f"- ok: {dict(report.get('security') or {}).get('ok', False)}",
        f"- findings: {dict(dict(report.get('security') or {}).get('summary') or {}).get('finding_count', 0)}",
        "",
        "## Backups",
        "",
        f"- roots: {', '.join(list(dict(report.get('backups') or {}).get('roots') or [])) or '--'}",
        f"- verified_recent: {dict(report.get('backups') or {}).get('verified_count', 0)}",
        f"- recent_seen: {dict(report.get('backups') or {}).get('recent_count', 0)}",
        "",
        "## Runtime",
        "",
        f"- profile: {dict(report.get('ops') or {}).get('active_profile', {}).get('profile_id', '')}",
        f"- autonomy_profile: {dict(report.get('ops') or {}).get('active_autonomy_profile', {}).get('profile_id', '')}",
        f"- background_running: {dict(dict(report.get('ops') or {}).get('background_tasks') or {}).get('running_count', 0)}",
        f"- observability_status: {dict(report.get('observability') or {}).get('status', 'idle')}",
        "",
        "## Continuity",
        "",
        f"- status: {dict(report.get('continuity') or {}).get('status', 'idle')}",
        f"- summary: {dict(report.get('continuity') or {}).get('summary', '')}",
        f"- resume_entries: {dict(report.get('continuity') or {}).get('entry_count', 0)}",
        "",
        "## Observability",
        "",
        f"- summary: {dict(report.get('observability') or {}).get('summary_line', '')}",
        f"- alerts: {dict(report.get('observability') or {}).get('alert_count', 0)}",
        f"- recovery_pressure: {dict(report.get('observability') or {}).get('recovery_pressure', 0)}",
        "",
        "## Context Budget",
        "",
        f"- status: {dict(report.get('context_budget') or {}).get('status', 'idle')}",
        f"- compacted_sessions: {dict(report.get('context_budget') or {}).get('compacted_session_count', 0)}",
        f"- pressure_threads: {dict(report.get('context_budget') or {}).get('pressure_count', 0)}",
        f"- latest_compacted_at: {dict(report.get('context_budget') or {}).get('latest_compacted_at', '') or '--'}",
        "",
        "## Release Reports",
        "",
        f"- latest: {dict(dict(report.get('release_reports') or {}).get('latest') or {}).get('report_id', '--')}",
        f"- history_count: {len(list(dict(report.get('release_reports') or {}).get('history') or []))}",
        "",
        "## Actions",
        "",
    ]
    actions = list(report.get("recommended_actions") or [])
    if not actions:
        lines.append("- none")
    else:
        for action in actions:
            lines.append(f"- {action}")
    lines.extend(["", "Observability:",])
    observability = dict(report.get("observability") or {})
    lines.append(f"- {observability.get('summary_line', '--')}")
    return "\n".join(lines) + "\n"


def build_support_bundle(root_dir: str | Path = ".", *, label: str = "") -> dict[str, Any]:
    root = Path(root_dir)
    doctor = run_somi_doctor(root)
    security = run_security_audit(root)
    backups = verify_recent_backups(root / "backups", limit=5)
    ops = OpsControlPlane(root_dir=root / "sessions" / "ops").snapshot(event_limit=12, metric_limit=24)
    observability = build_observability_digest(ops)
    context_budget = run_context_budget_status(root)
    state_store = SessionEventStore(db_path=root / "sessions" / "state" / "system_state.sqlite3")
    sessions = state_store.list_sessions(limit=12)
    task_graphs: dict[str, dict[str, Any]] = {}
    for session in sessions:
        thread_id = str(session.get("thread_id") or "").strip()
        if not thread_id or thread_id in task_graphs:
            continue
        task_graphs[thread_id] = load_task_graph(
            str(session.get("user_id") or "default_user"),
            thread_id,
            root_dir=root / "sessions" / "task_graph",
        )
    continuity = build_resume_ledger(
        sessions=sessions,
        background_snapshot=dict(ops.get("background_tasks") or {}),
        task_graphs=task_graphs,
        active_thread_id=str((sessions[0] or {}).get("thread_id") or "") if sessions else "",
        limit=8,
    )
    latest_release = load_latest_release_report(root)
    release_history = list_release_reports(root, limit=6)

    actions: list[str] = []
    actions.extend(str(item) for item in list(doctor.get("repair_suggestions") or []))
    actions.extend(str(item) for item in list(security.get("repair_suggestions") or []))
    actions.extend(str(item) for item in list(observability.get("recommendations") or []))
    actions.extend(str(item) for item in list(continuity.get("recommendations") or []))
    actions.extend(str(item) for item in list(context_budget.get("recommendations") or []))

    status = "ready"
    if not bool(doctor.get("ok")) or not bool(security.get("ok")):
        status = "warn"
    if int(backups.get("verified_count") or 0) <= 0:
        status = "blocked"

    deduped_actions: list[str] = []
    seen: set[str] = set()
    for action in actions:
        text = str(action or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped_actions.append(text)

    return {
        "generated_at": _now_iso(),
        "root_dir": str(root),
        "label": str(label or root.name),
        "status": status,
        "doctor": doctor,
        "security": security,
        "backups": backups,
        "ops": {
            "active_profile": dict(ops.get("active_profile") or {}),
            "active_autonomy_profile": dict(ops.get("active_autonomy_profile") or {}),
            "background_tasks": dict(ops.get("background_tasks") or {}),
            "policy_decision_counts": dict(ops.get("policy_decision_counts") or {}),
        },
        "observability": observability,
        "context_budget": context_budget,
        "continuity": continuity,
        "release_reports": {
            "latest": {
                "report_id": str(dict(latest_release or {}).get("report_id") or ""),
                "generated_at": str(dict(latest_release or {}).get("generated_at") or ""),
                "status": str(dict(latest_release or {}).get("status") or ""),
                "readiness_score": dict(latest_release or {}).get("readiness_score"),
            },
            "history": release_history,
        },
        "recommended_actions": deduped_actions,
    }


def write_support_bundle(
    root_dir: str | Path = ".",
    *,
    label: str = "",
    write_bundle: bool = True,
) -> dict[str, Any]:
    report = build_support_bundle(root_dir, label=label)
    if not write_bundle:
        return report

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_id = f"{stamp}_{_slug(str(label or Path(root_dir).name))}"
    support_dir = _support_dir(root_dir)
    json_path = support_dir / f"support_bundle_{bundle_id}.json"
    md_path = support_dir / f"support_bundle_{bundle_id}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_render_support_markdown(report), encoding="utf-8")
    persisted = dict(report)
    persisted["bundle_id"] = bundle_id
    persisted["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return persisted


def format_support_bundle(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Support Bundle]",
        f"- status: {report.get('status', '')}",
        f"- root_dir: {report.get('root_dir', '')}",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- backup_roots: {', '.join(list(dict(report.get('backups') or {}).get('roots') or [])) or '--'}",
        f"- verified_backups: {dict(report.get('backups') or {}).get('verified_count', 0)}",
        f"- doctor_ok: {dict(report.get('doctor') or {}).get('ok', False)}",
        f"- security_ok: {dict(report.get('security') or {}).get('ok', False)}",
        f"- observability: {dict(report.get('observability') or {}).get('status', 'idle')}",
        f"- context_budget: {dict(report.get('context_budget') or {}).get('status', 'idle')}",
        f"- continuity: {dict(report.get('continuity') or {}).get('status', 'idle')}",
        f"- latest_release: {dict(dict(report.get('release_reports') or {}).get('latest') or {}).get('report_id', '--') or '--'}",
    ]
    paths = dict(report.get("paths") or {})
    if paths:
        lines.append(f"- json: {paths.get('json', '')}")
        lines.append(f"- markdown: {paths.get('markdown', '')}")
    actions = list(report.get("recommended_actions") or [])
    lines.append("")
    lines.append("Actions:")
    if not actions:
        lines.append("- none")
    else:
        for action in actions[:8]:
            lines.append(f"- {action}")
    return "\n".join(lines)
