from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audit.recovery_drill import format_recovery_drill, run_recovery_drill
from audit.system_gauntlet import format_system_gauntlet, write_system_gauntlet_report
from gateway.federation import build_federation_snapshot, format_federation_snapshot
from ops import (
    build_continuity_recovery_snapshot,
    create_phase_backup,
    format_backup_creation,
    format_continuity_recovery_snapshot,
    format_context_budget_status,
    format_offline_pack_catalog,
    format_observability_snapshot,
    format_offline_resilience,
    format_security_audit,
    format_somi_doctor,
    build_offline_pack_catalog,
    run_observability_snapshot,
    run_context_budget_status,
    run_offline_resilience,
    run_security_audit,
    run_somi_doctor,
    verify_recent_backups,
)
from ops.framework_freeze import format_framework_freeze, write_framework_freeze
from ops.release_gate import diff_release_reports, format_release_diff, format_release_gate, run_release_gate
from ops.replay_harness import format_replay_harness, run_replay_harness
from ops.support_bundle import format_support_bundle, write_support_bundle


def _json_text(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="somi", description="Somi framework doctoring and release-readiness helpers.")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser("doctor", help="Run the general framework doctor.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    doctor_parser.add_argument("--apply-safe-repairs", action="store_true", help="Create missing baseline dirs and stores.")
    doctor_parser.add_argument("--root", default=".", help="Project root to inspect.")

    offline_parser = subparsers.add_parser("offline", help="Offline resilience helpers.")
    offline_subparsers = offline_parser.add_subparsers(dest="offline_command")
    offline_status_parser = offline_subparsers.add_parser("status", help="Inspect local degraded-network readiness.")
    offline_status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    offline_status_parser.add_argument("--root", default=".", help="Project root to inspect.")
    offline_catalog_parser = offline_subparsers.add_parser("catalog", help="Inspect the bundled offline knowledge-pack catalog.")
    offline_catalog_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    offline_catalog_parser.add_argument("--root", default=".", help="Project root to inspect.")
    offline_catalog_parser.add_argument("--runtime-mode", default="normal", help="Runtime mode such as normal or survival.")
    offline_catalog_parser.add_argument("--query", default="", help="Optional local query to test against bundled packs.")
    offline_catalog_parser.add_argument("--limit", type=int, default=6, help="Maximum preview hits to surface.")
    offline_federation_parser = offline_subparsers.add_parser("federation", help="Inspect the local store-and-forward node exchange.")
    offline_federation_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    offline_federation_parser.add_argument("--root", default=".", help="Project root to inspect.")
    offline_continuity_parser = offline_subparsers.add_parser("continuity", help="Inspect offline recovery domains and workflow coverage.")
    offline_continuity_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    offline_continuity_parser.add_argument("--root", default=".", help="Project root to inspect.")
    offline_continuity_parser.add_argument("--runtime-mode", default="normal", help="Runtime mode such as normal or survival.")
    offline_continuity_parser.add_argument("--query", default="", help="Optional recovery query to match against packs and workflows.")
    offline_continuity_parser.add_argument("--limit", type=int, default=4, help="Maximum workflow recommendations to surface.")
    offline_drill_parser = offline_subparsers.add_parser("drill", help="Run the blackout-style recovery drill.")
    offline_drill_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    offline_drill_parser.add_argument("--root", default=".", help="Project root to inspect.")
    offline_drill_parser.add_argument("--runtime-mode", default="survival", help="Runtime mode such as survival.")
    offline_drill_parser.add_argument("--scenario", default="blackout", help="Recovery scenario label.")

    observability_parser = subparsers.add_parser("observability", help="Runtime observability helpers.")
    observability_subparsers = observability_parser.add_subparsers(dest="observability_command")
    observability_snapshot_parser = observability_subparsers.add_parser("snapshot", help="Inspect runtime hotspots and recovery pressure.")
    observability_snapshot_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    observability_snapshot_parser.add_argument("--root", default=".", help="Project root to inspect.")

    context_parser = subparsers.add_parser("context", help="Context-budget and compaction helpers.")
    context_subparsers = context_parser.add_subparsers(dest="context_command")
    context_status_parser = context_subparsers.add_parser("status", help="Inspect conversation context pressure and compaction health.")
    context_status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    context_status_parser.add_argument("--root", default=".", help="Project root to inspect.")
    context_status_parser.add_argument("--user-id", default="", help="Optional user id filter.")

    security_parser = subparsers.add_parser("security", help="Security audit helpers.")
    security_subparsers = security_parser.add_subparsers(dest="security_command")
    security_audit_parser = security_subparsers.add_parser("audit", help="Run the security audit.")
    security_audit_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    security_audit_parser.add_argument("--root", default=".", help="Project root to inspect.")

    backup_parser = subparsers.add_parser("backup", help="Backup verification helpers.")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command")
    backup_create_parser = backup_subparsers.add_parser("create", help="Create a focused phase backup.")
    backup_create_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    backup_create_parser.add_argument("--root", default=".", help="Project root to back up.")
    backup_create_parser.add_argument("--label", required=True, help="Phase label for the backup directory.")
    backup_create_parser.add_argument(
        "--include",
        default="",
        help="Comma-separated file or directory paths to include. Defaults to the source-focused checkpoint set.",
    )
    backup_create_parser.add_argument(
        "--output-root",
        default="",
        help="Optional backup root. Defaults to audit/backups under the project root.",
    )

    backup_verify_parser = backup_subparsers.add_parser("verify", help="Verify recent backups.")
    backup_verify_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    backup_verify_parser.add_argument("--root", default=".", help="Project root to inspect.")

    replay_parser = subparsers.add_parser("replay", help="Replay a persisted session timeline.")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command")
    replay_session_parser = replay_subparsers.add_parser("session", help="Replay the latest or selected session.")
    replay_session_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    replay_session_parser.add_argument("--root", default=".", help="Project root to inspect.")
    replay_session_parser.add_argument("--user-id", default="default_user", help="User id whose session should be replayed.")
    replay_session_parser.add_argument("--thread-id", default="", help="Specific thread id to replay.")
    replay_session_parser.add_argument("--limit-turns", type=int, default=12, help="Maximum number of turns to inspect.")

    release_parser = subparsers.add_parser("release", help="Release readiness helpers.")
    release_subparsers = release_parser.add_subparsers(dest="release_command")

    release_gate_parser = release_subparsers.add_parser("gate", help="Run the release-readiness gate.")
    release_gate_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    release_gate_parser.add_argument("--root", default=".", help="Project root to inspect.")
    release_gate_parser.add_argument("--label", default="", help="Optional label for the persisted report.")
    release_gate_parser.add_argument("--no-write", action="store_true", help="Do not persist the release report.")

    release_diff_parser = release_subparsers.add_parser("diff", help="Compare two persisted release reports.")
    release_diff_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    release_diff_parser.add_argument("--root", default=".", help="Project root to inspect.")
    release_diff_parser.add_argument("--current", default="latest", help="Current report selector.")
    release_diff_parser.add_argument("--previous", default="previous", help="Previous report selector.")

    release_gauntlet_parser = release_subparsers.add_parser("gauntlet", help="Run the coordinated full-system gauntlet.")
    release_gauntlet_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    release_gauntlet_parser.add_argument("--root", default=".", help="Project root to inspect.")
    release_gauntlet_parser.add_argument("--prefix", default="system_gauntlet", help="Artifact prefix.")
    release_gauntlet_parser.add_argument("--output-dir", default="", help="Directory for gauntlet artifacts.")
    release_gauntlet_parser.add_argument("--packs", default="", help="Comma-separated gauntlet pack ids to run.")
    release_gauntlet_parser.add_argument("--count", type=int, default=100, help="Default count for the 100x gauntlet packs.")
    release_gauntlet_parser.add_argument("--scenario-turns", type=int, default=30, help="Target turn count for the average user pack.")
    release_gauntlet_parser.add_argument("--search-corpus", default="everyday100", help="Search corpus for the search gauntlet pack.")
    release_gauntlet_parser.add_argument("--skip-live-chat", action="store_true", help="Skip the live chat stress pass inside the gauntlet.")

    freeze_parser = subparsers.add_parser("freeze", help="Generate the framework-freeze and packaging-handoff artifacts.")
    freeze_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    freeze_parser.add_argument("--root", default=".", help="Project root to inspect.")
    freeze_parser.add_argument("--refresh-release-gate", action="store_true", help="Refresh the release gate before writing freeze artifacts.")

    support_parser = subparsers.add_parser("support", help="Support and diagnostics helpers.")
    support_subparsers = support_parser.add_subparsers(dest="support_command")
    support_bundle_parser = support_subparsers.add_parser("bundle", help="Generate a support bundle snapshot.")
    support_bundle_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    support_bundle_parser.add_argument("--root", default=".", help="Project root to inspect.")
    support_bundle_parser.add_argument("--label", default="", help="Optional label for the persisted bundle.")
    support_bundle_parser.add_argument("--no-write", action="store_true", help="Do not persist the support bundle.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "doctor":
        report = run_somi_doctor(Path(args.root), apply_repairs=bool(args.apply_safe_repairs))
        print(format_somi_doctor(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "offline" and args.offline_command == "status":
        report = run_offline_resilience(Path(args.root))
        print(format_offline_resilience(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "offline" and args.offline_command == "catalog":
        report = build_offline_pack_catalog(
            Path(args.root),
            runtime_mode=str(args.runtime_mode or "normal"),
            query=str(args.query or ""),
            limit=int(args.limit or 6),
        )
        print(format_offline_pack_catalog(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "offline" and args.offline_command == "federation":
        report = build_federation_snapshot(Path(args.root))
        print(format_federation_snapshot(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "offline" and args.offline_command == "continuity":
        report = build_continuity_recovery_snapshot(
            Path(args.root),
            runtime_mode=str(args.runtime_mode or "normal"),
            query=str(args.query or ""),
            limit=int(args.limit or 4),
        )
        print(format_continuity_recovery_snapshot(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "offline" and args.offline_command == "drill":
        report = run_recovery_drill(
            Path(args.root),
            runtime_mode=str(args.runtime_mode or "survival"),
            scenario=str(args.scenario or "blackout"),
        )
        print(format_recovery_drill(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "observability" and args.observability_command == "snapshot":
        report = run_observability_snapshot(Path(args.root))
        print(format_observability_snapshot(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "context" and args.context_command == "status":
        report = run_context_budget_status(Path(args.root), user_id=(str(args.user_id or "") or None))
        print(format_context_budget_status(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "security" and args.security_command == "audit":
        report = run_security_audit(Path(args.root))
        print(format_security_audit(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "backup" and args.backup_command == "create":
        include_paths = [item.strip() for item in str(args.include or "").split(",") if item.strip()]
        report = create_phase_backup(
            Path(args.root),
            label=str(args.label or ""),
            include_paths=include_paths or None,
            output_root=(str(args.output_root or "") or None),
        )
        print(format_backup_creation(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "backup" and args.backup_command == "verify":
        report = verify_recent_backups(Path(args.root) / "backups", limit=5)
        if args.json:
            print(_json_text(report))
        else:
            print("[Somi Backup Verify]")
            print(f"- verified_recent: {report.get('verified_count', 0)}")
            print(f"- recent_seen: {report.get('recent_count', 0)}")
        return 0 if int(report.get("verified_count") or 0) > 0 else 1

    if args.command == "replay" and args.replay_command == "session":
        report = run_replay_harness(
            Path(args.root),
            user_id=str(args.user_id or "default_user"),
            thread_id=str(args.thread_id or ""),
            limit_turns=int(args.limit_turns or 12),
        )
        print(format_replay_harness(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "release" and args.release_command == "gate":
        report = run_release_gate(
            Path(args.root),
            label=str(args.label or ""),
            write_report=not bool(args.no_write),
        )
        print(format_release_gate(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "release" and args.release_command == "diff":
        report = diff_release_reports(
            Path(args.root),
            current=str(args.current or "latest"),
            previous=str(args.previous or "previous"),
        )
        print(format_release_diff(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "release" and args.release_command == "gauntlet":
        selected = [item.strip() for item in str(args.packs or "").split(",") if item.strip()]
        report = write_system_gauntlet_report(
            root_dir=Path(args.root),
            output_dir=(str(args.output_dir or "") or str(Path(args.root) / "audit")),
            prefix=str(args.prefix or "system_gauntlet"),
            python_executable=sys.executable,
            selected_packs=selected,
            base_count=int(args.count or 100),
            scenario_turns=int(args.scenario_turns or 30),
            search_corpus=str(args.search_corpus or "everyday100"),
            include_live_chat=not bool(args.skip_live_chat),
        )
        print(format_system_gauntlet(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "freeze":
        report = write_framework_freeze(
            Path(args.root),
            refresh_release_gate=bool(args.refresh_release_gate),
        )
        print(format_framework_freeze(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("framework_core_ready", False)) else 1

    if args.command == "support" and args.support_command == "bundle":
        report = write_support_bundle(
            Path(args.root),
            label=str(args.label or ""),
            write_bundle=not bool(args.no_write),
        )
        print(format_support_bundle(report) if not args.json else _json_text(report))
        return 0 if str(report.get("status") or "") != "blocked" else 1

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
