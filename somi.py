from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ops import format_security_audit, format_somi_doctor, run_security_audit, run_somi_doctor, verify_recent_backups
from ops.framework_freeze import format_framework_freeze, write_framework_freeze
from ops.release_gate import diff_release_reports, format_release_diff, format_release_gate, run_release_gate
from ops.replay_harness import format_replay_harness, run_replay_harness


def _json_text(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="somi", description="Somi framework doctoring and release-readiness helpers.")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser("doctor", help="Run the general framework doctor.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    doctor_parser.add_argument("--apply-safe-repairs", action="store_true", help="Create missing baseline dirs and stores.")
    doctor_parser.add_argument("--root", default=".", help="Project root to inspect.")

    security_parser = subparsers.add_parser("security", help="Security audit helpers.")
    security_subparsers = security_parser.add_subparsers(dest="security_command")
    security_audit_parser = security_subparsers.add_parser("audit", help="Run the security audit.")
    security_audit_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    security_audit_parser.add_argument("--root", default=".", help="Project root to inspect.")

    backup_parser = subparsers.add_parser("backup", help="Backup verification helpers.")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command")
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

    freeze_parser = subparsers.add_parser("freeze", help="Generate the framework-freeze and packaging-handoff artifacts.")
    freeze_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    freeze_parser.add_argument("--root", default=".", help="Project root to inspect.")
    freeze_parser.add_argument("--refresh-release-gate", action="store_true", help="Refresh the release gate before writing freeze artifacts.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "doctor":
        report = run_somi_doctor(Path(args.root), apply_repairs=bool(args.apply_safe_repairs))
        print(format_somi_doctor(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("ok", False)) else 1

    if args.command == "security" and args.security_command == "audit":
        report = run_security_audit(Path(args.root))
        print(format_security_audit(report) if not args.json else _json_text(report))
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

    if args.command == "freeze":
        report = write_framework_freeze(
            Path(args.root),
            refresh_release_gate=bool(args.refresh_release_gate),
        )
        print(format_framework_freeze(report) if not args.json else _json_text(report))
        return 0 if bool(report.get("framework_core_ready", False)) else 1

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
