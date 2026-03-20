from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.champion_scorecard import build_champion_scorecard, build_finality_summary, render_champion_scorecard_markdown
from ops.release_gate import load_latest_release_report, run_release_gate


FREEZE_DIR = Path("sessions/release_gate")
RELEASE_DOCS_DIR = Path("docs/release")
PHASE_SETS: dict[str, tuple[str, ...]] = {
    "neoupgrade": (
        "Finality Lab Backbone",
        "Secure Coding Sandbox Matrix",
        "Champion Coding Agent",
        "Research Supermode",
        "Evidence Graph and Research Exports",
        "Skill Forge and Self-Expansion",
        "Skill Marketplace and Trust Layer",
        "Node Mesh and Pairing",
        "Security-Centric Remote Execution",
        "Ontology Actions and Human Oversight",
        "Prestige UX and Cross-Surface Continuity",
        "Champion Freeze and Publish Gate",
    ),
    "upgrade": (
        "Benchmark Baseline and Gap Ledger",
        "Gateway 2.0 Skeleton",
        "Pairing, Presence, and Remote Session Trust",
        "Tool and Skill Ecosystem 2.0",
        "Coding OS 2.0",
        "OCR and Document Intelligence 2.0",
        "Browser and Desktop Automation",
        "Knowledge Vault and Memory Retrieval 2.0",
        "Security Doctor and Auto-Repair",
        "Agent Studio and Recipe Packs",
        "Observability, Replay, and Release Gate",
        "Framework Freeze Before Packaging",
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _phase_config(root: Path) -> dict[str, Any]:
    backups_root = root / "backups"
    release_notes = root / "docs" / "release" / "FRAMEWORK_RELEASE_NOTES.md"
    if (root / "neoupgrade.md").exists() or any(backups_root.glob("neoupgrade_phase*_start_*")):
        return {
            "prefix": "neoupgrade",
            "roadmap_path": release_notes,
            "titles": PHASE_SETS["neoupgrade"],
        }
    return {
        "prefix": "upgrade",
        "roadmap_path": release_notes,
        "titles": PHASE_SETS["upgrade"],
    }


def _phase_rows(root: Path) -> list[dict[str, Any]]:
    config = _phase_config(root)
    prefix = str(config.get("prefix") or "upgrade")
    roadmap_path = Path(config.get("roadmap_path") or (root / "docs" / "release" / "FRAMEWORK_RELEASE_NOTES.md"))
    phase_titles = tuple(config.get("titles") or ())
    rows: list[dict[str, Any]] = []
    for phase, title in enumerate(phase_titles, start=1):
        complete_paths = sorted((root / "backups").glob(f"{prefix}_phase{phase:02d}_complete_*"))
        start_paths = sorted((root / "backups").glob(f"{prefix}_phase{phase:02d}_start_*"))
        next_start_paths = sorted((root / "backups").glob(f"{prefix}_phase{phase + 1:02d}_start_*")) if phase < len(phase_titles) else []
        if phase == 1 and not complete_paths and not start_paths:
            rows.append(
                {
                    "phase": phase,
                    "title": title,
                    "status": "completed" if roadmap_path.exists() else "missing",
                    "evidence": str(roadmap_path if roadmap_path.exists() else ""),
                    "checkpoint": str(roadmap_path if roadmap_path.exists() else ""),
                    "checkpoint_type": "roadmap",
                    "has_start_backup": False,
                    "has_complete_backup": False,
                }
            )
            continue
        checkpoint = complete_paths[-1] if complete_paths else (next_start_paths[-1] if next_start_paths else None)
        checkpoint_type = "complete_backup" if complete_paths else ("next_phase_start" if next_start_paths else "")
        start_checkpoint = start_paths[-1] if start_paths else None
        rows.append(
            {
                "phase": phase,
                "title": title,
                "status": "completed" if checkpoint else ("started" if start_checkpoint else "missing"),
                "evidence": str(checkpoint or start_checkpoint or ""),
                "checkpoint": str(checkpoint or ""),
                "checkpoint_type": checkpoint_type,
                "has_start_backup": bool(start_checkpoint),
                "has_complete_backup": bool(complete_paths),
            }
        )
    return rows


def _architecture_refs(root: Path) -> list[dict[str, Any]]:
    refs = [
        root / "docs" / "architecture" / "system_manifest.json",
        root / "docs" / "architecture" / "SYSTEM_MAP.md",
        root / "docs" / "architecture" / "BOUNDARIES.md",
        root / "docs" / "architecture" / "TRUST_BOUNDARIES.md",
    ]
    return [
        {
            "path": str(path),
            "exists": path.exists(),
            "last_modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() if path.exists() else "",
        }
        for path in refs
    ]


def _packaging_handoff() -> list[dict[str, str]]:
    return [
        {
            "id": "installer_bootstrap",
            "title": "Packaging and installer bootstrap",
            "detail": "Build the cross-platform installer/setup flow, environment doctor, and first-run dependency bootstrap.",
        },
        {
            "id": "distribution_profiles",
            "title": "Distribution profiles",
            "detail": "Define desktop, portable, and enterprise packaging targets with predictable default models and providers.",
        },
        {
            "id": "first_run_onboarding",
            "title": "First-run onboarding",
            "detail": "Guide model selection, approvals, gateway pairing, speech check, and coding workspace readiness for ordinary users.",
        },
        {
            "id": "gui_polish",
            "title": "Final GUI polish chapter",
            "detail": "Push the PySide6 shell into the final futuristic pass: motion, layout density, onboarding, and packaging-aware UX.",
        },
        {
            "id": "cross_platform_smoke",
            "title": "Cross-platform smoke matrix",
            "detail": "Run installer and launch smoke tests on Windows, Linux, and macOS targets before public release.",
        },
    ]


def build_framework_freeze(
    root_dir: str | Path = ".",
    *,
    user_id: str = "default_user",
    refresh_release_gate: bool = False,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    release_report = load_latest_release_report(root)
    if refresh_release_gate or release_report is None:
        release_report = run_release_gate(root, user_id=user_id, label="framework-freeze", write_report=True)

    phase_rows = _phase_rows(root)
    completed_phases = sum(1 for row in phase_rows if str(row.get("status")) == "completed")
    blockers = list(release_report.get("blockers") or [])
    warnings = list(release_report.get("warnings") or [])
    core_status = "stable" if not blockers and not warnings else ("stable_with_warnings" if not blockers else "blocked")
    finality_summary = build_finality_summary(root)
    champion_scorecard = dict(release_report.get("champion_scorecard") or build_champion_scorecard(root_dir=root, release_report=release_report, finality_summary=finality_summary))
    publish_highlights = [
        "Unified local AI operating system across chat, coding, research, speech, workflows, ontology, and node operations.",
        f"Measured finality captured for {finality_summary.get('measured_count', 0)}/{finality_summary.get('pack_count', 0)} core branches.",
        "Node mesh, approvals, and remote audit give Somi a publicly shippable trust model for distributed power.",
        "Flagship operator surfaces now include Control Room, Coding Studio, Research Studio, Speech controls, and Node Manager.",
    ]

    return {
        "generated_at": _now_iso(),
        "root_dir": str(root),
        "core_status": core_status,
        "framework_core_ready": not blockers,
        "packaging_ready": not blockers and not warnings,
        "release_report_id": str(release_report.get("report_id") or ""),
        "release_summary": {
            "status": str(release_report.get("status") or ""),
            "readiness_score": float(release_report.get("readiness_score") or 0.0),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "architecture_refs": _architecture_refs(root),
        "verified_upgrade_path": phase_rows,
        "completed_phase_count": completed_phases,
        "total_phase_count": len(phase_rows),
        "confirmed_release_blockers": blockers,
        "confirmed_release_warnings": warnings,
        "finality_summary": finality_summary,
        "champion_scorecard": champion_scorecard,
        "publish_highlights": publish_highlights,
        "packaging_handoff": _packaging_handoff(),
    }


def _render_framework_freeze_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Framework Freeze",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Core status: {report.get('core_status')}",
        f"Framework core ready: {bool(report.get('framework_core_ready'))}",
        f"Packaging ready: {bool(report.get('packaging_ready'))}",
        f"Release report: {report.get('release_report_id')}",
        "",
        "## Summary",
        "",
        f"- Completed phases: {report.get('completed_phase_count', 0)}/{report.get('total_phase_count', 0)}",
        f"- Release status: {dict(report.get('release_summary') or {}).get('status', '')}",
        f"- Release score: {dict(report.get('release_summary') or {}).get('readiness_score', 0.0)}",
        f"- Confirmed blockers: {dict(report.get('release_summary') or {}).get('blocker_count', 0)}",
        f"- Confirmed warnings: {dict(report.get('release_summary') or {}).get('warning_count', 0)}",
        "",
        "## Publish Highlights",
        "",
    ]
    for item in list(report.get("publish_highlights") or []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Finality Summary",
        "",
        f"- Run ID: {dict(report.get('finality_summary') or {}).get('run_id', '')}",
        f"- Difficulty: {dict(report.get('finality_summary') or {}).get('difficulty', '')}",
        f"- Measured branches: {dict(report.get('finality_summary') or {}).get('measured_count', 0)}/{dict(report.get('finality_summary') or {}).get('pack_count', 0)}",
        f"- Average time to finality: {dict(report.get('finality_summary') or {}).get('average_time_to_finality_ms', 0.0)} ms",
        "",
        "## Architecture References",
        "",
    ])
    for row in list(report.get("architecture_refs") or []):
        lines.append(f"- {row.get('path')}: exists={row.get('exists')} modified={row.get('last_modified')}")
    lines.append("")
    lines.append("## Upgrade Path")
    lines.append("")
    for row in list(report.get("verified_upgrade_path") or []):
        lines.append(f"- Phase {row.get('phase')}: {row.get('title')} [{row.get('status')}]")
        if row.get("evidence"):
            lines.append(f"  evidence={row.get('evidence')} ({row.get('checkpoint_type') or 'evidence'})")
    lines.append("")
    lines.append("## Champion Scorecard")
    lines.append("")
    lines.append(f"- Verdict: {dict(report.get('champion_scorecard') or {}).get('overall_verdict', '')}")
    lines.append(f"- Categories ahead: {dict(report.get('champion_scorecard') or {}).get('ahead_count', 0)}")
    lines.append("")
    lines.append("## Confirmed Release Blockers")
    lines.append("")
    blockers = list(report.get("confirmed_release_blockers") or [])
    if blockers:
        for row in blockers:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Confirmed Release Warnings")
    lines.append("")
    warnings = list(report.get("confirmed_release_warnings") or [])
    if warnings:
        for row in warnings:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Packaging Handoff")
    lines.append("")
    for row in list(report.get("packaging_handoff") or []):
        lines.append(f"- {row.get('title')}: {row.get('detail')}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_upgrade_path_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Upgrade Path Verified",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
    ]
    for row in list(report.get("verified_upgrade_path") or []):
        lines.append(f"## Phase {row.get('phase')}: {row.get('title')}")
        lines.append("")
        lines.append(f"- Status: {row.get('status')}")
        lines.append(f"- Evidence: {row.get('evidence') or 'missing'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_blockers_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release Blockers",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Core status: {report.get('core_status')}",
        "",
        "## Blockers",
        "",
    ]
    blockers = list(report.get("confirmed_release_blockers") or [])
    if blockers:
        for row in blockers:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    warnings = list(report.get("confirmed_release_warnings") or [])
    if warnings:
        for row in warnings:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_packaging_handoff_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Packaging Handoff",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Next Chapter",
        "",
    ]
    for row in list(report.get("packaging_handoff") or []):
        lines.append(f"- {row.get('title')}: {row.get('detail')}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_release_notes_markdown(report: dict[str, Any]) -> str:
    finality = dict(report.get("finality_summary") or {})
    scorecard = dict(report.get("champion_scorecard") or {})
    lines = [
        "# Framework Release Notes",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Why Publish Now",
        "",
        f"- {scorecard.get('overall_verdict', 'Somi is ready for public comparison.')}",
        f"- Release status: {dict(report.get('release_summary') or {}).get('status', '')}",
        f"- Release score: {dict(report.get('release_summary') or {}).get('readiness_score', 0.0)}",
        f"- Finality measured: {finality.get('measured_count', 0)}/{finality.get('pack_count', 0)}",
        "",
        "## Highlights",
        "",
    ]
    for item in list(report.get("publish_highlights") or []):
        lines.append(f"- {item}")
    lines.extend(["", "## Neo Chapter Coverage", ""])
    for row in list(report.get("verified_upgrade_path") or []):
        lines.append(f"- Phase {row.get('phase')}: {row.get('title')} [{row.get('status')}]")
    lines.extend(["", "## Remaining Focus", ""])
    warnings = list(report.get("confirmed_release_warnings") or [])
    if warnings:
        for row in warnings:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- Packaging, installer flow, and final onboarding remain the next chapter.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_framework_freeze(
    root_dir: str | Path = ".",
    *,
    user_id: str = "default_user",
    refresh_release_gate: bool = False,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    report = build_framework_freeze(root, user_id=user_id, refresh_release_gate=refresh_release_gate)
    freeze_dir = root / FREEZE_DIR
    docs_dir = root / RELEASE_DOCS_DIR
    freeze_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    json_payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    freeze_markdown = _render_framework_freeze_markdown(report)
    upgrade_markdown = _render_upgrade_path_markdown(report)
    blockers_markdown = _render_blockers_markdown(report)
    handoff_markdown = _render_packaging_handoff_markdown(report)
    champion_markdown = render_champion_scorecard_markdown(dict(report.get("champion_scorecard") or {}))
    release_notes_markdown = _render_release_notes_markdown(report)

    (freeze_dir / "framework_freeze.json").write_text(json_payload, encoding="utf-8")
    (freeze_dir / "framework_freeze.md").write_text(freeze_markdown, encoding="utf-8")
    (freeze_dir / "latest_framework_freeze.json").write_text(json_payload, encoding="utf-8")
    (freeze_dir / "latest_framework_freeze.md").write_text(freeze_markdown, encoding="utf-8")

    (docs_dir / "FRAMEWORK_FREEZE.md").write_text(freeze_markdown, encoding="utf-8")
    (docs_dir / "UPGRADE_PATH_VERIFIED.md").write_text(upgrade_markdown, encoding="utf-8")
    (docs_dir / "RELEASE_BLOCKERS.md").write_text(blockers_markdown, encoding="utf-8")
    (docs_dir / "PACKAGING_HANDOFF.md").write_text(handoff_markdown, encoding="utf-8")
    (docs_dir / "CHAMPION_SCORECARD.md").write_text(champion_markdown, encoding="utf-8")
    (docs_dir / "FRAMEWORK_RELEASE_NOTES.md").write_text(release_notes_markdown, encoding="utf-8")
    return report


def load_latest_framework_freeze(root_dir: str | Path = ".") -> dict[str, Any] | None:
    return _read_json(Path(root_dir) / FREEZE_DIR / "latest_framework_freeze.json")


def format_framework_freeze(report: dict[str, Any]) -> str:
    return (
        "[Somi Framework Freeze]\n"
        f"- core_status: {report.get('core_status')}\n"
        f"- framework_core_ready: {bool(report.get('framework_core_ready'))}\n"
        f"- packaging_ready: {bool(report.get('packaging_ready'))}\n"
        f"- completed_phases: {report.get('completed_phase_count', 0)}/{report.get('total_phase_count', 0)}\n"
        f"- blockers: {len(list(report.get('confirmed_release_blockers') or []))}\n"
        f"- warnings: {len(list(report.get('confirmed_release_warnings') or []))}\n"
    )
